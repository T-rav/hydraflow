"""Post-implementation skill-gate machinery for the implement runner.

The check → repair → re-check engine behind ``AgentRunner._run_skill``:
one full gate evaluation (finder loop, deterministic coverage delta,
independent verifier), the bounded repair-in-run loop (#11593 seam 1), and
the ``skill_results.json`` telemetry appender. Extracted from ``agent.py``
when the #11593 repair seam pushed it over the god-file mass threshold —
same decomposition as ``implement_quality_gate.py`` for the post-build gate.

``AgentRunner`` keeps thin delegating methods for every function here:
tests (and the repair loop itself) patch seams on the runner instance
(``_execute``, ``_git_head``, ``_run_skill_repair_pass``,
``_run_coverage_delta_check``, …), and the delegates preserve those patch
points. Functions therefore call back through ``runner.<method>`` rather
than each other directly.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from adequacy_demand import DemandVerdict, evaluate_demand, split_findings
from coverage_delta import (
    compute_uncovered_changed_lines,
    parse_cobertura_covered_lines,
    parse_diff_changed_lines,
)
from exception_classify import reraise_on_credit_or_bug
from file_util import atomic_write
from models import LoopResult

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agent import AgentRunner
    from models import Task
    from skill_registry import AgentSkill
    from tracing_context import TracingContext

logger = logging.getLogger("hydraflow.skill_gate")

#: What produced a failing gate verdict (#11593 seam 3 telemetry).
VerdictSource = Literal["llm-fail", "verifier-override", "coverage-delta"]

#: Summary recorded when the demand contract (#11644) finds the pinned demand
#: closed and only new, unlocatable findings left. Distinct from a plain OK so
#: the manifest says *why* the run cleared the gate.
PIN_CLOSED_SUMMARY = "pinned test-adequacy demand closed"


@dataclass(slots=True)
class SkillCheckOutcome:
    """One full evaluation of a skill gate: finder loop + coverage + verifier.

    ``verdict_source`` and ``findings`` describe the failing verdict (both
    empty on a pass); ``short_circuit`` marks the no-op cases (empty diff,
    empty prompt) that must return without telemetry or repair.

    ``pinned`` is the demand the previous attempt stated (#11644) and
    ``demand`` is how this evaluation's findings partitioned against it —
    which of them block, which are new, which were absorbed as advisory.
    """

    result: LoopResult
    verdict_source: VerdictSource | None = None
    findings: list[str] = field(default_factory=list)
    short_circuit: bool = False
    pinned: list[str] = field(default_factory=list)
    demand: DemandVerdict = field(default_factory=DemandVerdict)


def skill_demand_pin(
    runner: AgentRunner, skill: AgentSkill, pinned: Sequence[str]
) -> list[str]:
    """Resolve the pinned demand actually in force for *skill* (#11644).

    Empty unless the skill declares a ``pin_config_key``, that config field
    is true, and the caller supplied a previous attempt's demand. Read via
    ``getattr`` on every gate evaluation so the knob stays live-editable —
    same convention as ``skill_repair_budget``.
    """
    if skill.pin_config_key is None or not pinned:
        return []
    if not getattr(runner._config, skill.pin_config_key, False):
        return []
    return [f for f in pinned if f.strip()]


def _stated_findings(findings: list[str], summary: str) -> list[str]:
    """The demand a failing verdict actually stated.

    A finder or verifier that reports RETRY/OVERRIDE without a ``GAPS:`` block
    still states its demand — in the summary line. Recovering it matters twice:
    the #11644 contract has something to judge instead of an empty list, and
    the #11593 repair prompt gets a demand instead of "(see summary above)".
    Split the same way the calibration instrument splits a legacy manifest's
    error string, so runtime and instrument enumerate findings identically.
    """
    return findings or list(split_findings(summary))


def _merge_advisory(demand: DemandVerdict, carried: Sequence[str]) -> DemandVerdict:
    """Fold an earlier stage's absorbed findings into a later stage's partition.

    A run can be flipped by the finder's contract and then still rejected by
    the coverage delta or the verifier. The findings the first flip absorbed
    are what makes the moving bar measurable, so they must survive the later
    stage rather than being overwritten by it.
    """
    if not carried:
        return demand
    seen = set(demand.advisory)
    extra = tuple(f for f in carried if f not in seen)
    if not extra:
        return demand
    return replace(demand, advisory=(*demand.advisory, *extra))


def _apply_demand_contract(
    result: LoopResult,
    findings: list[str],
    pinned: list[str],
    issue_id: int,
    source: VerdictSource,
    carried_advisory: Sequence[str] = (),
) -> tuple[LoopResult, DemandVerdict]:
    """Judge a failing LLM verdict against the pinned demand (#11644).

    Returns the (possibly flipped) result plus the partition. With no pin in
    force this is a no-op that still records the anchored/unanchored split.
    Only the LLM-sourced verdicts route through here: a deterministic
    coverage-delta failure is anchored by construction and always blocks.

    Fail-closed guard: a verdict from which no finding text can be recovered
    at all is left rejecting. Nothing was stated, so nothing can be shown
    closed — without this a bare ``RETRY`` with an empty summary would waive
    itself.
    """
    if not findings:
        return result, _merge_advisory(
            DemandVerdict(pinned_enforced=bool(pinned)), carried_advisory
        )
    demand = _merge_advisory(
        evaluate_demand(findings, pinned, pinned_enforced=bool(pinned)),
        carried_advisory,
    )
    if demand.blocks:
        return result, demand
    logger.info(
        "test-adequacy pinned demand closed for #%d (%s): %d new unanchored "
        "finding(s) recorded as advisory",
        issue_id,
        source,
        len(demand.advisory),
    )
    return (
        LoopResult(
            passed=True,
            summary=PIN_CLOSED_SUMMARY,
            attempts=result.attempts,
        ),
        demand,
    )


async def run_skill_check(
    runner: AgentRunner,
    skill: AgentSkill,
    issue: Task,
    worktree_path: Path,
    branch: str,
    max_attempts: int,
    plan_text: str,
    pinned_findings: Sequence[str] = (),
) -> SkillCheckOutcome:
    """One full gate evaluation: finder loop, coverage delta, verifier.

    Re-reads the branch diff on every call so a post-repair re-check
    (#11593) judges the repaired worktree, not the diff the first check
    saw. The failing verdict's source and concrete findings ride the
    outcome for the repair prompt and the rejection telemetry.

    ``pinned_findings`` (#11644) is the demand the previous attempt stated.
    When it is in force, each LLM-sourced failing verdict is judged against
    it before the run is rejected: a finding restating the pin blocks, a
    genuinely new finding blocks only if it names a locatable referent, and
    a new unlocatable finding is absorbed as advisory. The deterministic
    coverage delta and the verifier both still run after a flip, so nothing
    downstream of the finder is skipped by it.
    """
    pinned = skill_demand_pin(runner, skill, pinned_findings)
    full_diff = await runner._get_branch_diff(worktree_path, branch)
    if not full_diff.strip():
        return SkillCheckOutcome(
            result=LoopResult(passed=True, summary="Empty diff"),
            short_circuit=True,
        )

    max_diff = runner._config.max_review_diff_chars
    prompt_diff = (
        full_diff[:max_diff] + f"\n[Diff truncated at {max_diff:,} chars]"
        if len(full_diff) > max_diff
        else full_diff
    )

    prompt = skill.prompt_builder(
        issue_number=issue.id,
        issue_title=issue.title,
        diff=prompt_diff,
        plan_text=plan_text,
    )
    if not prompt.strip():
        return SkillCheckOutcome(
            result=LoopResult(passed=True, summary=f"{skill.name}: no input data"),
            short_circuit=True,
        )

    cmd = runner._build_pre_quality_review_command()
    summary = ""
    # The finder transcript feeds the verifier's explicit-OK trigger below.
    # Initialised for the type checker; the attempt loop always runs at
    # least once (max_attempts <= 0 returns early in _run_skill), and an
    # empty transcript can never carry the explicit OK marker.
    transcript = ""
    findings: list[str] = []

    # Each iteration's _execute call allocates its own subprocess_idx
    # from BaseRunner's monotonic counter, so retries and back-to-back
    # skills never overwrite each other's subprocess-N.json files.
    for attempt in range(1, max_attempts + 1):
        transcript = await runner._execute(
            cmd,
            prompt,
            worktree_path,
            {"issue": issue.id, "source": "implementer"},
            issue_labels=issue.tags,
            # #9998: tag telemetry with the skill name (not the coarse
            # phase source) so prompt-efficiency ordering keys match the
            # adversarial corpus's expected_catcher names.
            telemetry_source=skill.name,
        )
        passed, summary, findings = skill.result_parser(transcript)
        if passed:
            result = LoopResult(passed=True, summary=summary, attempts=attempt)
            break
        if findings:
            logger.info(
                "%s findings for #%d: %s",
                skill.name,
                issue.id,
                "; ".join(findings[:5]),
            )
    else:
        result = LoopResult(passed=False, summary=summary, attempts=max_attempts)

    verdict_source: VerdictSource | None = None if result.passed else "llm-fail"

    # #11644 demand contract, applied BEFORE the coverage delta and the
    # verifier so a flipped verdict still faces both. Applying it at the end
    # would let a retry skip the deterministic coverage check entirely, which
    # would be a real weakening rather than a bounded demand.
    demand = DemandVerdict()
    if not result.passed:
        findings = _stated_findings(findings, result.summary)
        result, demand = _apply_demand_contract(
            result, findings, pinned, issue.id, "llm-fail"
        )
        if result.passed:
            verdict_source = None

    # Coverage delta runs once after the LLM attempt loop — not per-attempt.
    # Running make coverage on each retry is expensive and redundant because
    # the worktree code doesn't change between LLM attempts. (A repair
    # re-check re-enters this function, so repaired code IS re-measured.)
    if result.passed and skill.coverage_check:
        uncovered = await runner._run_coverage_delta_check(
            worktree_path, full_diff, issue.id
        )
        if uncovered:
            cov_summary = (
                f"Coverage delta: {len(uncovered)} uncovered changed line(s): "
                + "; ".join(uncovered[:5])
                + (f" (+ {len(uncovered) - 5} more)" if len(uncovered) > 5 else "")
            )
            logger.info(
                "coverage-delta findings for #%d: %s",
                issue.id,
                "; ".join(uncovered[:5]),
            )
            result = LoopResult(
                passed=False,
                summary=cov_summary,
                attempts=result.attempts,
            )
            verdict_source = "coverage-delta"
            findings = uncovered
            # Deliberately NOT routed through the demand contract: uncovered
            # changed lines are anchored by construction (`path:line`) and a
            # deterministic gap must keep overriding an LLM OK (#11593).
            demand = _merge_advisory(
                DemandVerdict(
                    blocking=tuple(uncovered),
                    anchored=tuple(uncovered),
                    pinned_enforced=demand.pinned_enforced,
                ),
                demand.advisory,
            )

    # Independent verifier (#9546): a second-opinion pass with its own
    # model, gated on the finder's EXPLICIT OK marker — never on the
    # no-marker default-pass (empty fake/garbled transcripts must not grow
    # an extra dispatch). Runs after the deterministic coverage check so a
    # coverage override skips the extra LLM spend.
    if (
        result.passed
        and skill.verifier is not None
        and getattr(runner._config, skill.verifier.enabled_config_key, False)
        and skill.verifier.trigger(transcript)
    ):
        result, verifier_gaps = await runner._run_skill_verifier(
            skill, issue, worktree_path, prompt_diff, result
        )
        if not result.passed:
            verdict_source = "verifier-override"
            findings = _stated_findings(verifier_gaps, result.summary)
            # The override arm routes through the same contract as the finder
            # (#11644): its threshold, model independence and explicit-OK
            # trigger are untouched — only what its findings may DEMAND is.
            result, demand = _apply_demand_contract(
                result,
                findings,
                pinned,
                issue.id,
                "verifier-override",
                carried_advisory=demand.advisory,
            )
            if result.passed:
                verdict_source = None

    if result.passed:
        verdict_source = None
        # Absorbed findings are the measurement of the moving bar (#11644),
        # so they survive a pass; a plain clean verdict still carries none.
        findings = list(demand.advisory)
    return SkillCheckOutcome(
        result=result,
        verdict_source=verdict_source,
        findings=findings,
        pinned=pinned,
        demand=demand,
    )


async def run_skill_repair_loop(
    runner: AgentRunner,
    skill: AgentSkill,
    issue: Task,
    worktree_path: Path,
    branch: str,
    max_attempts: int,
    plan_text: str,
    check: SkillCheckOutcome,
) -> tuple[SkillCheckOutcome, list[str]]:
    """Bounded repair-in-run for a failing gate verdict (#11593 seam 1).

    Hands the concrete findings back to the implementer worktree for up
    to ``skill.repair_config_key`` focused fix passes, re-running the
    FULL check (coverage delta + independent verifier included) after
    each. Never weakens the gate: the final verdict is always the
    re-checked one; a pass that writes nothing — or after which the diff
    vanished — burns its pass and the standing failing verdict proceeds
    to rejection. Returns the final check outcome plus per-pass outcome
    labels (``verdict-flipped`` / ``still-failing`` / ``no-change``).
    """
    repair_outcomes: list[str] = []
    budget = runner._skill_repair_budget(skill)
    while not check.result.passed and len(repair_outcomes) < budget:
        pass_number = len(repair_outcomes) + 1
        pass_started = time.monotonic()
        changed = await runner._run_skill_repair_pass(
            skill, issue, worktree_path, check, pass_number, budget
        )
        if changed:
            recheck = await runner._run_skill_check(
                skill,
                issue,
                worktree_path,
                branch,
                max_attempts,
                plan_text,
                # The re-check faces the SAME pinned demand as the first
                # check (#11644) — a repair pass must not silently widen or
                # narrow the bar it was told to close.
                pinned_findings=check.pinned,
            )
            if recheck.short_circuit:
                # The diff vanished mid-repair. Keep the standing failing
                # verdict — a repair pass must never wash the gate out.
                outcome = "no-change"
            else:
                check = recheck
                outcome = "verdict-flipped" if check.result.passed else "still-failing"
        else:
            # Wrote nothing: burn the pass and proceed to rejection on the
            # standing verdict instead of re-checking unchanged code.
            outcome = "no-change"
        repair_outcomes.append(outcome)
        logger.info(
            "%s repair pass %d/%d for #%d: %s",
            skill.name,
            pass_number,
            budget,
            issue.id,
            outcome,
        )
        ctx = runner._tracing_ctx
        if ctx is not None:
            runner._append_skill_result(
                ctx,
                skill_name=f"{skill.name}-repair",
                passed=check.result.passed,
                attempts=pass_number,
                duration_seconds=time.monotonic() - pass_started,
                blocking=skill.blocking,
                role="repair",
                outcome=outcome,
            )
        if outcome == "no-change":
            break
    return check, repair_outcomes


def skill_repair_budget(runner: AgentRunner, skill: AgentSkill) -> int:
    """Resolve the bounded repair-pass budget for *skill* (#11593).

    0 when the skill declares no repair seam or the config field is 0 —
    straight to rejection, the pre-#11593 behavior. Read via ``getattr``
    on every gate evaluation so the setting stays live-editable.
    """
    if skill.repair_config_key is None or skill.repair_prompt_builder is None:
        return 0
    return max(0, getattr(runner._config, skill.repair_config_key, 0))


async def run_skill_repair_pass(
    runner: AgentRunner,
    skill: AgentSkill,
    issue: Task,
    worktree_path: Path,
    check: SkillCheckOutcome,
    pass_number: int,
    max_passes: int,
) -> bool:
    """Dispatch one focused repair pass to the implementer worktree.

    Returns ``True`` when the pass changed the branch (HEAD moved —
    worth a full re-check), ``False`` when it wrote nothing so the
    caller burns the pass. Fails open to the re-check when HEAD cannot
    be read: the verifier-checked re-check is the authority, and a
    burned pass on a git hiccup would reject a possibly-repaired run.
    """
    builder = skill.repair_prompt_builder
    if builder is None:  # pragma: no cover — skill_repair_budget gates
        return False
    head_before = await runner._git_head(worktree_path)
    prompt = builder(
        issue_number=issue.id,
        issue_title=issue.title,
        verdict_source=check.verdict_source or "llm-fail",
        summary=check.result.summary,
        # The demand the run must close. #11644 splits it: anchored findings
        # are handed over as-is, unanchored ones carry a locate-it-first
        # instruction, and findings the pin absorbed ride along as advisory
        # so the pass is never told to chase a bar that no longer blocks.
        findings=list(check.demand.blocking) or check.findings,
        anchored_findings=list(check.demand.anchored),
        advisory_findings=list(check.demand.advisory),
        pass_number=pass_number,
        max_passes=max_passes,
    )
    cmd = runner._build_command(worktree_path)
    await runner._execute(
        cmd,
        prompt,
        worktree_path,
        {"issue": issue.id, "source": "implementer"},
        issue_labels=issue.tags,
        telemetry_source=f"{skill.name}-repair",
    )
    await runner._force_commit_uncommitted(issue, worktree_path)
    head_after = await runner._git_head(worktree_path)
    if not head_before or not head_after:
        return True
    return head_after != head_before


async def git_head(runner: AgentRunner, worktree_path: Path) -> str:
    """Return the worktree's HEAD SHA, or ``""`` when it cannot be read."""
    try:
        result = await runner._runner.run_simple(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            timeout=runner._config.git_command_timeout,
        )
    except (TimeoutError, FileNotFoundError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


async def run_coverage_delta_check(
    runner: AgentRunner,
    worktree_path: Path,
    diff: str,
    issue_id: int,
) -> list[str]:
    """Run ``make coverage 0`` and return uncovered changed-line refs.

    Returns a list of ``path:line`` strings for changed production lines
    that the test suite does not exercise.  Returns an empty list when
    make fails, times out, or no coverage XML is produced — preserving
    the LLM verdict in those cases.
    """
    try:
        timeout_secs = runner._config.test_adequacy_coverage_timeout_secs
        cov_result = await runner._runner.run_simple(
            ["make", "coverage", "0"],
            cwd=str(worktree_path),
            timeout=float(timeout_secs),
        )
    except (TimeoutError, FileNotFoundError):
        logger.warning(
            "Coverage delta check failed for #%d (timeout or make not found)",
            issue_id,
        )
        return []
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning(
            "Coverage delta check unexpected error for #%d: %s", issue_id, exc
        )
        return []

    if cov_result.returncode != 0:
        logger.warning(
            "Coverage delta: make coverage 0 returned rc=%d for #%d",
            cov_result.returncode,
            issue_id,
        )
        return []

    coverage_xml = worktree_path / "coverage.xml"
    if not coverage_xml.is_file():
        logger.warning(
            "Coverage delta: coverage.xml not found at %s for #%d",
            coverage_xml,
            issue_id,
        )
        return []

    changed = parse_diff_changed_lines(diff)
    covered = parse_cobertura_covered_lines(coverage_xml, worktree_path)
    return compute_uncovered_changed_lines(changed, covered)


def append_skill_result(
    runner: AgentRunner,
    ctx: TracingContext,
    *,
    skill_name: str,
    passed: bool,
    attempts: int,
    duration_seconds: float,
    blocking: bool,
    role: str = "finder",
    outcome: str | None = None,
) -> None:
    """Append a skill result to <run-N>/skill_results.json.

    *role* tags the entry for telemetry (#9546): ``"finder"`` for the
    skill's own pass/fail loop, ``"verifier"`` for the independent
    second-opinion pass, ``"repair"`` for a #11593 repair pass. *outcome*
    is per-role detail (verifier: ``concur`` / ``override`` / ``degraded``;
    repair: ``verdict-flipped`` / ``still-failing`` / ``no-change``).

    Never raises — tracing must not crash the agent run.
    """
    try:
        run_dir = (
            runner._config.data_root
            / "traces"
            / str(ctx.issue_number)
            / ctx.phase
            / f"run-{ctx.run_id}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        results_path = run_dir / "skill_results.json"
        existing: list[dict[str, Any]] = []
        if results_path.exists():
            try:
                existing = json.loads(results_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                existing = []
        existing.append(
            {
                "skill_name": skill_name,
                "passed": passed,
                "attempts": attempts,
                "duration_seconds": round(duration_seconds, 3),
                "blocking": blocking,
                "role": role,
                "outcome": outcome,
            }
        )
        atomic_write(results_path, json.dumps(existing, indent=2))
    except Exception:
        logger.warning(
            "Failed to append skill result for %s", skill_name, exc_info=True
        )

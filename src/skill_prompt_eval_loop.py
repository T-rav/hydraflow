"""SkillPromptEvalLoop — weekly corpus backstop + weak-case audit.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.6. Two roles:

1. **Backstop.** Runs the *full* adversarial corpus weekly (§4.1). Once
   the corpus grows past `trust_rc_subset_size` the RC gate shifts to a
   sampled subset; this loop catches regressions the weekly sample
   misses. Files `skill-prompt-drift` issues for PASS→FAIL transitions.
2. **Weak-case audit.** Samples 10% of `provenance: learning-loop`
   cases and flags any whose `expected_catcher` skill passes them — a
   weak-case signal the §4.1 v2 learner uses. Files `corpus-case-weak`
   issues for human triage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from auto_pr import PREFLIGHT_DOCS_ONLY, generate_and_open_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps
from escalation_reconcile import EscalationReconciler
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from models import WorkCycleResult
from prompt_efficiency import (
    INEFFICIENCY_THRESHOLD,
    SkillEfficiencyRow,
    compute_skill_efficiency,
    format_scorecard,
    pick_refine_order,
)
from prompt_refiner import (
    PROMPT_LENGTH_DRIFT_LIMIT,
    REFINABLE_SKILLS,
    SKILL_BUILDER_MODULES,
    assemble_refine_context,
    check_tripwires,
    discover_validation_case_ids,
    length_drift_exceeds,
    parse_patch_response,
    render_builder_prompt,
)
from prompt_telemetry import PromptTelemetry
from runner_utils import run_lightweight_agent
from subprocess_util import SubprocessTimeoutError, run_subprocess_result

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.skill_prompt_eval_loop")

_MAX_ATTEMPTS = 3
_WEAK_SAMPLE_RATE = 0.10

# Marker label on the HITL escalation issue. Single-sourced so the filing
# path (`_file_escalation`) and the reconciler can never drift apart — no
# config knob exists for this label (unlike e.g. fake_coverage_stuck_label).
_STUCK_LABEL = "skill-prompt-stuck"

# Parses ``_file_escalation`` titles back to the ``case_id`` subject.
# ``(.+?)`` — see flake_tracker: whitespace-bounded captures make any
# spaced subject permanently unreconcilable. Case IDs are machine-named
# today; the anchored non-greedy capture costs nothing.
_ESCALATION_TITLE_RE = re.compile(r"^HITL: skill prompt drift (.+?) unresolved after ")


def _escalation_subject(title: str) -> str | None:
    m = _ESCALATION_TITLE_RE.match(title)
    return m.group(1) if m else None


# Hard cap on the subprocess read. A wedged child must not hang the loop cycle
# forever and freeze its heartbeat — the #9410 silent-stall failure class
# (#9454 / #9508). ``make trust-adversarial`` drives an LLM eval harness so it
# gets a generous bound. (The former ``gh`` reconcile read now goes through
# the PRPort via the shared ``EscalationReconciler``.) Bounded (and, via
# ``run_subprocess_result``, process-group hardened — #9554/#10028) rather
# than a raw ``create_subprocess_exec``.
_ADVERSARIAL_TIMEOUT_SECONDS = 3600


# --- Prompt self-refinement (#9724) ------------------------------------------

# Labels attached to an auto-refinement PR. Minimal + descriptive; auto_pr
# ensures the label exists on the repo before ``gh pr create``.
_REFINE_PR_LABELS = ("skill-prompt-refine",)

# Hard bound on the one-shot refine LLM synthesis call.
_REFINE_LLM_TIMEOUT_SECONDS = 300

# Hard bound on the `git status --porcelain` changed-set check. A fast local
# git call; generous enough to absorb a slow filesystem without masking a
# genuinely wedged git process.
_GIT_STATUS_TIMEOUT_SECONDS = 30

# Cases dir, relative to a repo/worktree root, holding the adversarial corpus.
_CASES_REL = "tests/trust/adversarial/cases"

# Human-readable note commented on the drift issue per non-shipping outcome.
_REFINE_OUTCOME_NOTES = {
    "tripwire": (
        "the candidate patch tripped a safety gate — it touched a path outside "
        "the target builder module or drifted the rendered prompt length past "
        "the ±30% limit"
    ),
    "validation_failed": (
        "the candidate patch failed live re-validation against the regressed "
        "case, the held-out honeypots, or the benign sentinels"
    ),
    "error": "a refinement patch could not be synthesized for this case",
}


async def _assert_only_module_changed(worktree: Path, module_rel: str) -> None:
    """Assert git's ACTUAL changed-set in *worktree* is exactly ``{module_rel}``.

    Closes the git-apply prefix-differential bypass: ``git apply`` defaults to
    ``-p1`` (strips ANY single leading path component from every side of every
    section in the patch), but ``check_tripwires``/``_collect_patch_targets``
    only recognize the literal ``a/``/``b/`` prefixes. A patch section headed
    e.g. ``--- x/tests/trust/adversarial/corpus_runner.py`` /
    ``+++ y/tests/trust/adversarial/corpus_runner.py`` applies cleanly under
    ``-p1`` yet contributes zero targets to the tripwire scan — a bundled
    patch that mixes one legit ``a/``/``b/`` section against the allowed
    builder module with one such section against the validation harness would
    pass ``check_tripwires``, rewrite the harness on disk, and could forge an
    all-PASS validation. Whatever prefix scheme the patch itself used,
    ``git status --porcelain`` reports the ground truth of what changed on
    disk; comparing that against the single expected target closes the bypass
    regardless of how the patch tried to name its victim path.

    Call this immediately after applying the patch and before any further
    gate (length drift, live validation) runs against the worktree.

    Raises ``RuntimeError`` naming the unexpected/missing paths when the
    touched set is not exactly ``{module_rel}`` — modified, added, and
    untracked files all count as "touched". A timeout also raises
    ``RuntimeError`` (``SubprocessTimeoutError``, via the shared bounded
    helper) — the caller's ``except RuntimeError`` treats it the same as a
    path tripwire, a safe default for an unexplained wedged git status.
    """
    try:
        result = await run_subprocess_result(
            "git",
            "status",
            "--porcelain",
            cwd=worktree,
            timeout=_GIT_STATUS_TIMEOUT_SECONDS,
        )
    except SubprocessTimeoutError as exc:
        raise RuntimeError(
            f"git status timed out after {_GIT_STATUS_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr[:400]
        msg = f"git status failed (rc={result.returncode}): {detail}"
        raise RuntimeError(msg)

    touched: set[str] = set()
    for idx, line in enumerate(result.stdout.splitlines()):
        if not line:
            continue
        # Porcelain v1 shape: 2 status chars + a space + the path, so the
        # separator is always at a fixed index 2. BUT `result.stdout` comes
        # from `run_subprocess_result` -> `HostRunner.run_simple`, whose
        # `SimpleResult.stdout` is `.strip()`-ped across the WHOLE blob — if
        # the first status char is itself a space (e.g. " M path", modified
        # in the worktree but not staged), that leading space is eaten,
        # shifting the first line left by one and corrupting a fixed
        # `line[3:]` slice (observed: "src/x.py" -> "rc/x.py"). Detect the
        # shift instead of assuming a fixed offset: a well-formed
        # (unshifted) line always has its separator at index 2; only the
        # shifted first line can have it at index 1.
        if len(line) > 2 and line[2] == " ":
            rest = line[3:]
        elif idx == 0 and len(line) > 1 and line[1] == " ":
            rest = line[2:]
        else:
            rest = line[3:]
        old, sep, new = rest.partition(" -> ")
        if sep:
            touched.add(old.strip())
            touched.add(new.strip())
        else:
            touched.add(rest.strip())

    if touched != {module_rel}:
        msg = (
            f"patch touched unexpected paths: expected only {module_rel!r}, "
            f"found {sorted(touched)!r}"
        )
        raise RuntimeError(msg)


def _all_required_pass(results_json: str) -> bool:
    """True iff every non-SKIPPED result in *results_json* is PASS.

    The honeypot validation gate's pure result-parsing core, factored out of
    :meth:`SkillPromptEvalLoop._validate_candidate` so it can be unit-tested
    without the corpus-runner subprocess plumbing. Fails CLOSED on every
    degenerate shape — malformed/non-JSON stdout, a non-list payload, an empty
    result set, or an all-SKIPPED set all return ``False``. A candidate we
    could not positively prove passed the regressed case + 100% of holdouts +
    benign sentinels must never ship.
    """
    try:
        results = json.loads(results_json or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(results, list):
        return False
    non_skipped = [
        r for r in results if isinstance(r, dict) and r.get("status") != "SKIPPED"
    ]
    if not non_skipped:
        return False
    return all(r.get("status") == "PASS" for r in non_skipped)


class _RefineLLM(Protocol):
    """Minimal one-shot text-completion seam for refine synthesis.

    Tests inject a fake; production lazily builds :class:`_CLIRefineLLM`.
    """

    async def complete(self, prompt: str) -> str: ...


class _CLIRefineLLM:
    """Production refine client: one-shot RAW-text completion via the shared
    lightweight-agent seam (CH-6 gated, telemetried, credit-aware).

    Returns the CLI's raw stdout so the caller can parse the ```diff fence —
    unlike ``ClaudeCLIClient.complete_structured`` (which parses JSON), refine
    output is a unified diff, not a structured object. Never exercised under
    test; the loop's ``refine_llm`` kwarg injects a fake for all unit coverage.
    """

    def __init__(self, config: HydraFlowConfig, model: str) -> None:
        self._config = config
        self._model = model

    async def complete(self, prompt: str) -> str:
        result = await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model=self._model,
            prompt=prompt,
            source="skill_prompt_refine",
            timeout=float(_REFINE_LLM_TIMEOUT_SECONDS),
            issue_labels=(),
        )
        if result.returncode != 0:
            msg = f"refine LLM failed (rc={result.returncode}): {result.stderr[:200]}"
            raise RuntimeError(msg)
        return result.stdout


class SkillPromptEvalLoop(BaseBackgroundLoop):
    """Weekly skill-prompt drift detector + corpus-health auditor (spec §4.6)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        refine_llm: _RefineLLM | None = None,
    ) -> None:
        super().__init__(
            worker_name="skill_prompt_eval",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        # Injected fake under test; production lazily builds `_CLIRefineLLM`.
        self._refine_llm = refine_llm
        # Telemetry consumption (spec §5) — same construction idiom as every
        # other PromptTelemetry consumer (base_runner, post_merge_handler,
        # base_subprocess_runner): no injection seam, just `PromptTelemetry
        # (config)`. Tests seed real records via `loop._telemetry.record(...)`.
        self._telemetry = PromptTelemetry(config)
        self._escalations = EscalationReconciler(
            prs=pr_manager,
            dedup=dedup,
            key_prefix="skill_prompt_eval",
            stuck_label=_STUCK_LABEL,
            clear_attempts=state.clear_skill_prompt_attempts,
            subject_from_title=_escalation_subject,
        )

    def _get_default_interval(self) -> int:
        return self._config.skill_prompt_eval_interval

    async def _run_corpus(self) -> list[dict[str, Any]]:
        """Invoke `make trust-adversarial` → list of case-result dicts.

        Each dict carries ``{case_id, skill, status, provenance,
        expected_catcher}``. Owned by Plan 1 (`make trust-adversarial
        --format=json`). Missing keys are tolerated — cases without
        ``provenance`` are treated as ``hand-crafted``.

        The ``HYDRAFLOW_TRUST_ADVERSARIAL_MAX_CASES`` env var is
        forwarded so the harness can bound LLM spend pre-execution
        when the corpus grows beyond the cap. The Python-side cap
        below is the operator-visible backstop.
        """
        cmd = ["make", "trust-adversarial", "FORMAT=json"]
        try:
            result = await run_subprocess_result(
                *cmd,
                cwd=self._config.repo_root,
                timeout=_ADVERSARIAL_TIMEOUT_SECONDS,
                extra_env={
                    "HYDRAFLOW_TRUST_ADVERSARIAL_MAX_CASES": str(
                        self._config.skill_prompt_eval_max_corpus_cases
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning("trust-adversarial subprocess failed: %s", exc)
            return []
        if result.returncode not in (0, 1):  # 1 = failures present; still valid output
            logger.warning(
                "trust-adversarial exit=%d: %s",
                result.returncode,
                result.stderr[:400],
            )
            return []
        try:
            return json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            logger.warning("trust-adversarial non-JSON response")
            return []

    @staticmethod
    def _drift_title(case: dict[str, Any]) -> str:
        # Single source so the file path and the close-on-recovery path can never
        # drift apart (#9359 / fake-fidelity lesson).
        return (
            f"Skill prompt drift: {case.get('skill', '?')} "
            f"missed {case.get('case_id', '?')}"
        )

    async def _resolve_drift_issue(self, case: dict[str, Any]) -> None:
        """Close the open drift issue when a case is passing again (#9359)."""
        existing = await self._pr.find_existing_issue(self._drift_title(case))
        if existing:
            await self._pr.post_comment(
                existing, "Skill-prompt case is passing again — auto-closing."
            )
            await self._pr.close_issue(existing)

    async def _file_drift_issue(self, case: dict[str, Any], last_status: str) -> int:
        title = self._drift_title(case)
        body = (
            f"## Regression\n\n"
            f"Case `{case.get('case_id')}` regressed "
            f"**{last_status} → {case.get('status')}** on "
            f"skill `{case.get('skill')}`.\n\n"
            f"**Expected catcher:** `{case.get('expected_catcher', '?')}`\n"
            f"**Provenance:** `{case.get('provenance', 'unknown')}`\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop. Standard "
            f"repair path: edit the skill prompt or the skill's code._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "skill-prompt-drift"]
        )

    async def _file_weak_case_issue(self, case: dict[str, Any]) -> int:
        title = (
            f"Weak corpus case: {case.get('case_id')} "
            f"bypassed {case.get('expected_catcher')}"
        )
        body = (
            f"## Weak-case signal\n\n"
            f"Learning-loop case `{case.get('case_id')}` was PASSED by the "
            f"skill (`{case.get('skill')}`) that was *expected* to catch it "
            f"(`{case.get('expected_catcher')}`). This is the weak-case "
            f"signal the §4.1 v2 learner uses — flag it for human review "
            f"so the corpus self-improves.\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "corpus-case-weak"]
        )

    async def _file_escalation(self, case_id: str, attempts: int) -> int:
        title = f"HITL: skill prompt drift {case_id} unresolved after {attempts}"
        body = (
            f"`skill_prompt_eval` filed `skill-prompt-drift` for `{case_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", _STUCK_LABEL]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for closed `skill-prompt-stuck` escalations.

        Delegates to the shared :class:`EscalationReconciler` (PRPort-based;
        replaced the raw ``gh issue list`` subprocess). Subjects are parsed
        from the escalation title shape
        ``"HITL: skill prompt drift <case_id> unresolved after N"``.
        """
        await self._escalations.reconcile_closed()

    def _sample_learning_cases(
        self, cases: list[dict[str, Any]], seed: int = 0
    ) -> list[dict[str, Any]]:
        learning = [c for c in cases if c.get("provenance") == "learning-loop"]
        if not learning:
            return []
        n = max(1, math.ceil(len(learning) * _WEAK_SAMPLE_RATE))
        rng = random.Random(seed or 1)
        return rng.sample(learning, min(n, len(learning)))

    async def _do_work(self) -> WorkCycleResult:
        """Weekly eval — backstop + weak-case sampling."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.skill_prompt_eval_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        cases = await self._run_corpus()
        if not cases:
            return {"status": "no_cases", "filed": 0}

        # Defense-in-depth cap. The harness should honor
        # HYDRAFLOW_TRUST_ADVERSARIAL_MAX_CASES (passed via env in
        # _run_corpus) to bound LLM spend pre-execution; this Python-side
        # cap bounds operator-visible escalation flooding even if the
        # harness ran more cases than configured. Sample deterministically
        # using the per-tick seed.
        cap = self._config.skill_prompt_eval_max_corpus_cases
        capped = len(cases) > cap
        if capped:
            logger.warning(
                "skill-prompt-eval: corpus has %d cases, capping to %d",
                len(cases),
                cap,
            )
            rng = random.Random(int(time.time() * 1_000_000))
            cases = rng.sample(cases, cap)

        # Telemetry consumption (spec §5) — ranked scorecard + refine-queue
        # priority ordering + `prompt-inefficiency` issue filing, using the
        # baseline stored on the *previous* tick for trend comparison.
        ordered_cases, efficiency_scorecard = await self._consume_efficiency_telemetry(
            cases
        )

        # Role 1 — backstop. PASS→FAIL regressions.
        last_green = self._state.get_skill_prompt_last_green()
        current: dict[str, str] = {
            c["case_id"]: c.get("status", "UNKNOWN") for c in cases
        }
        filed = 0
        escalated = 0
        resolved = 0
        dedup = self._dedup.get()
        # Per-tick seed: stable within one invocation, diverse across ticks
        # (matches plan decision #5 — seed-stable per workflow run).
        tick_seed = int(t0 * 1_000_000)
        # Most cost-inefficient skill's regression gets first crack at the
        # weekly refine cap (`ordered_cases`, not `cases` — the latter stays
        # in corpus order for `current`/weak-case sampling below).
        for case in ordered_cases:
            case_id = case.get("case_id")
            if not case_id:
                continue
            was = last_green.get(case_id, "PASS")
            now = case.get("status")
            key = f"skill_prompt_eval:{case_id}"
            if was == "PASS" and now == "FAIL":
                if key in dedup:
                    continue
                attempts = self._state.inc_skill_prompt_attempts(case_id)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(case_id, attempts)
                    escalated += 1
                else:
                    await self._file_drift_issue(case, was)
                    filed += 1
                    # Attempt a self-refinement PR (#9724). Wrapped so any
                    # failure counts an attempt + comments the outcome but never
                    # breaks the drift-issue flow above.
                    await self._try_refine(case)
                dedup.add(key)
                self._dedup.set_all(dedup)
            elif now == "PASS" and key in dedup:
                # Recovery — the case passes again. Close the open drift issue
                # and clear its dedup/attempts so a future regression re-files
                # (#9359 issue-hygiene).
                await self._resolve_drift_issue(case)
                dedup.discard(key)
                self._dedup.set_all(dedup)
                self._state.clear_skill_prompt_attempts(case_id)
                resolved += 1

        # Save the new snapshot — tests that currently PASS become the
        # new last-green. Tests that remain FAIL stay in the dedup set.
        self._state.set_skill_prompt_last_green(
            {cid: "PASS" for cid, status in current.items() if status == "PASS"}
        )

        # Role 2 — weak-case audit. Learning-loop cases that expected
        # catcher passed through.
        weak_flagged = 0
        sample = self._sample_learning_cases(cases, seed=tick_seed)
        for case in sample:
            skill = case.get("skill")
            catcher = case.get("expected_catcher")
            status = case.get("status")
            if skill == catcher and status == "PASS":
                key = f"skill_prompt_eval:weak:{case.get('case_id')}"
                if key in dedup:
                    continue
                await self._file_weak_case_issue(case)
                weak_flagged += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        # Open-escalation re-verify: drift fixed by a later PR — or a case
        # retired from the corpus — auto-closes its stuck escalation instead
        # of waiting for a human (#9618 class). Runs only on a COMPLETED
        # full-corpus run: a failed `make trust-adversarial` yields no cases
        # and early-returns above, and a capped tick only *sampled* the
        # corpus (an escalated case absent from the sample must not read as
        # "recovered") — pass None so the pass is skipped.
        active_subjects = (
            None
            if capped
            else {case_id for case_id, status in current.items() if status != "PASS"}
        )
        autoclosed = await self._escalations.reconcile_open(active_subjects)

        self._emit_trace(t0, cases_seen=len(cases))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "resolved": resolved,
            "autoclosed": autoclosed,
            "weak_cases_flagged": weak_flagged,
            "cases_seen": len(cases),
            "efficiency_scorecard": efficiency_scorecard,
        }

    # --- Telemetry consumption (spec §5) --------------------------------------

    async def _consume_efficiency_telemetry(
        self, cases: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str]:
        """Weekly telemetry rollup: scorecard + refine-priority ordering +
        inefficiency issue filing, then advance the baseline.

        Both `self._telemetry.get_source_totals()` and the stored baseline
        are LIFETIME-CUMULATIVE snapshots (never reset) — `compute_skill_
        efficiency` derives the marginal *window* since the previous tick
        from their deltas rather than comparing cumulative averages, or a
        real regression would be diluted into noise by a source's lifetime
        history. Trend is computed against the baseline stored on the
        *previous* tick (trailing-window: current vs. immediately preceding
        tick — not a multi-week rolling average). The baseline is
        overwritten with this tick's snapshot only AFTER that comparison, so
        next tick's window is relative to what this tick just measured.
        """
        totals_by_source = self._telemetry.get_source_totals()
        baseline = self._state.get_prompt_efficiency_baseline()
        rows = compute_skill_efficiency(totals_by_source, baseline)
        scorecard = format_scorecard(rows)
        ordered_cases = pick_refine_order(cases, rows)
        for row in rows:
            if (
                row.trend_vs_baseline is not None
                and row.trend_vs_baseline > INEFFICIENCY_THRESHOLD
            ):
                await self._file_inefficiency_issue(row)
        self._state.set_prompt_efficiency_baseline(totals_by_source)
        return ordered_cases, scorecard

    async def _file_inefficiency_issue(self, row: SkillEfficiencyRow) -> None:
        """File a deduped `prompt-inefficiency` issue for a degraded source."""
        dedup = self._dedup.get()
        key = f"skill_prompt_eval:inefficiency:{row.source}"
        if key in dedup:
            return
        title = f"Prompt inefficiency: {row.source} cost-per-call regressed"
        trend_pct = (
            f"{row.trend_vs_baseline:+.0%}"
            if row.trend_vs_baseline is not None
            else "n/a"
        )
        body = (
            f"## Cost-per-call regression\n\n"
            f"Source `{row.source}` cost-per-call is **{trend_pct}** vs. last "
            f"week's baseline — now ${row.cost_per_call:.4f}/call across "
            f"{row.calls} calls (${row.est_cost_usd:.4f} total, "
            f"{row.anomalies} usage anomalies).\n\n"
            f"_Spec §5c — filed by `skill_prompt_eval` loop's weekly "
            f"telemetry consumption. Standard repair path: check for "
            f"context bloat, cache-hit-rate drops, or a model swap for this "
            f"source._"
        )
        await self._pr.create_issue(
            title, body, ["hydraflow-find", "prompt-inefficiency"]
        )
        dedup.add(key)
        self._dedup.set_all(dedup)

    def _emit_trace(self, t0: float, *, cases_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["make", "trust-adversarial", "FORMAT=json"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"cases_seen={cases_seen}",
        )

    # --- Prompt self-refinement (#9724) --------------------------------------

    async def _try_refine(self, case: dict[str, Any]) -> str:
        """Drift-triggered skill-prompt self-refinement.

        Returns one of ``proposed | capped | disabled | not_refinable |
        tripwire | validation_failed | error``. On any outcome other than
        ``proposed``/``disabled``/``capped``/``not_refinable`` the case's
        repair-attempt counter is bumped and the outcome is noted on the open
        drift issue, so a stuck auto-refine still walks the case toward HITL
        escalation. ``not_refinable`` (a skill with no held-out honeypot
        coverage) is benign like ``disabled``/``capped``: no attempt burned,
        nothing commented. Refinement failure is fully contained here — it never
        propagates into the drift-issue flow that invoked it. That containment
        covers the outcome bookkeeping too: a PR-API hiccup while bumping the
        attempt counter or commenting the outcome must not escape and abort
        the remaining cases in the caller's tick.
        """
        case_id = str(case.get("case_id", ""))
        try:
            outcome = await self._compute_refine_outcome(case)
        except Exception as exc:  # classify credit/bug, else fail-soft
            reraise_on_credit_or_bug(exc)
            logger.warning("refine crashed for %s: %s", case_id, exc)
            outcome = "error"
        if outcome not in ("proposed", "disabled", "capped", "not_refinable"):
            try:
                attempts = self._state.inc_skill_prompt_attempts(case_id)
                await self._comment_refine_outcome(case, outcome, attempts)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "refine outcome bookkeeping failed for %s (%s): %s",
                    case_id,
                    outcome,
                    exc,
                )
        return outcome

    @staticmethod
    def _refine_skill_eligibility(skill_name: str) -> str | None:
        """Non-shipping early outcome if *skill_name* can't be auto-refined,
        else ``None`` (it may proceed to synthesis).

        ``error`` — no builder module registered at all (an unknown catcher
        name; a misconfiguration worth a repair attempt + drift comment).
        ``not_refinable`` — a known builder skill whose corpus carries no
        held-out honeypots yet: the overfit guard auto-refinement relies on
        (validate against 100% of holdouts) cannot run, so we never auto-merge
        a candidate we can't prove didn't overfit. Benign, distinct from
        ``error`` — it burns no repair attempt and posts no drift comment
        (the drift issue was already filed by the normal flow).
        """
        if skill_name not in SKILL_BUILDER_MODULES:
            logger.warning("refine: no builder module registered for %r", skill_name)
            return "error"
        if skill_name not in REFINABLE_SKILLS:
            logger.info(
                "refine: %r has no held-out honeypot coverage — not refinable",
                skill_name,
            )
            return "not_refinable"
        return None

    async def _compute_refine_outcome(self, case: dict[str, Any]) -> str:
        cfg = self._config
        if not cfg.skill_prompt_refine_enabled:
            return "disabled"
        now = datetime.now(UTC)
        if (
            self._state.refine_proposals_last_7d(now)
            >= cfg.skill_prompt_refine_max_weekly
        ):
            return "capped"
        skill_name = str(case.get("expected_catcher") or case.get("skill") or "")
        ineligible = self._refine_skill_eligibility(skill_name)
        if ineligible is not None:
            return ineligible
        case_id = str(case["case_id"])
        case_dir = cfg.repo_root / _CASES_REL / case_id
        try:
            context = assemble_refine_context(
                cfg.repo_root,
                case_dir,
                skill_name,
                failure_transcript=str(case.get("summary", "")),
            )
            response = await self._refine_llm_complete(context)
            patch_text = parse_patch_response(response)
        except (ValueError, RuntimeError) as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("refine synthesis failed for %s: %s", case_id, exc)
            return "error"

        reasons = check_tripwires(patch_text, skill_name, cfg.repo_root)
        if reasons:
            logger.warning("refine path/corpus tripwire for %s: %s", case_id, reasons)
            return "tripwire"

        return await self._open_refine_pr(
            case=case,
            skill_name=skill_name,
            case_id=case_id,
            patch_text=patch_text,
            now=now,
        )

    async def _open_refine_pr(
        self,
        *,
        case: dict[str, Any],
        skill_name: str,
        case_id: str,
        patch_text: str,
        now: datetime,
    ) -> str:
        """Generate the patched builder in a worktree, validate it, and open the
        auto-merge PR. Validation runs inside ``generate`` so a bad candidate
        aborts before any commit/push. Returns
        ``proposed | tripwire | validation_failed | error``.
        """
        cfg = self._config
        module_rel = SKILL_BUILDER_MODULES[skill_name]
        flags = {"ok": False, "length_tripwire": False, "path_tripwire": False}
        # Resolve the drift issue (filed earlier this tick) so the PR body can
        # name its provenance with an auto-linking `#N`. Read-only lookup;
        # `find_existing_issue` returns 0 when unmatched → the body falls back
        # to a title reference (see `_refine_pr_body`).
        drift_issue = await self._pr.find_existing_issue(self._drift_title(case))

        async def _generate(worktree: Path) -> None:
            # Validate INSIDE the generate callback so a bad candidate aborts
            # before any commit/push/PR (raising here → failed AutoPrResult).
            module_path = worktree / module_rel
            before = await asyncio.to_thread(
                render_builder_prompt, module_path, skill_name
            )
            await self._apply_patch_in_worktree(worktree, patch_text)
            # Git-native ground truth on what the patch actually touched —
            # closes the git-apply `-p1` prefix-differential bypass that
            # `check_tripwires`'s literal `a/`/`b/` scan cannot see (#9724
            # review). Must run before the length gate/validation below.
            try:
                await _assert_only_module_changed(worktree, module_rel)
            except RuntimeError:
                flags["path_tripwire"] = True
                raise
            after = await asyncio.to_thread(
                render_builder_prompt, module_path, skill_name
            )
            if length_drift_exceeds(before, after):
                flags["length_tripwire"] = True
                msg = "candidate prompt length drift exceeds limit"
                raise RuntimeError(msg)
            flags["ok"] = await self._validate_candidate(worktree, skill_name, case_id)
            if not flags["ok"]:
                msg = "candidate failed corpus/holdout validation"
                raise RuntimeError(msg)

        result = await generate_and_open_pr_async(
            repo_root=cfg.repo_root,
            branch=f"bot/prompt-refine-{case_id}",
            generate=_generate,
            # Prompt-refine PRs stage a single prompt module already vetted by
            # corpus/holdout validation in `_generate`; ruff on the staged diff
            # is the relevant check — docs-only preflight set (#10013).
            preflight=PREFLIGHT_DOCS_ONLY,
            path_specs=[module_rel],
            pr_title=(
                f"fix(prompt): refine {skill_name} — corpus case {case_id} regressed"
            ),
            pr_body=lambda: self._refine_pr_body(case, skill_name, drift_issue),
            base=cfg.base_branch(),
            auto_merge=True,
            gh_token="",
            raise_on_failure=False,
            commit_author_name=cfg.git_user_name,
            commit_author_email=cfg.git_user_email,
            labels=list(_REFINE_PR_LABELS),
        )
        if result.status == "opened":
            self._state.record_refine_proposal(now.isoformat())
            logger.info("refine proposed PR for %s: %s", case_id, result.pr_url)
            return "proposed"
        if flags["length_tripwire"] or flags["path_tripwire"]:
            return "tripwire"
        if not flags["ok"]:
            return "validation_failed"
        # The candidate validated but the PR still failed to open (git/gh
        # transient). Not the case's fault, but still non-shipping.
        logger.warning(
            "refine PR open failed for %s despite valid candidate: status=%r err=%r",
            case_id,
            result.status,
            result.error,
        )
        return "error"

    async def _refine_llm_complete(self, prompt: str) -> str:
        """Complete *prompt* via the injected fake or a lazily-built CLI client."""
        if self._refine_llm is None:
            model = (
                self._config.skill_prompt_refine_model
                or self._config.background_model
                or "sonnet"
            )
            self._refine_llm = _CLIRefineLLM(self._config, model)
        return await self._refine_llm.complete(prompt)

    async def _apply_patch_in_worktree(self, worktree: Path, patch_text: str) -> None:
        """Apply *patch_text* to *worktree* via ``git apply --whitespace=nowarn -``.

        Raises ``RuntimeError`` on a non-zero exit so the caller's generate
        callback aborts (→ no PR) when a candidate patch doesn't apply
        cleanly. A timeout also raises ``RuntimeError``
        (``SubprocessTimeoutError``, via the shared bounded helper) rather
        than a bare ``TimeoutError``.
        """
        try:
            result = await run_subprocess_result(
                "git",
                "apply",
                "--whitespace=nowarn",
                "-",
                cwd=worktree,
                stdin_input=patch_text.encode(),
                timeout=60,
            )
        except SubprocessTimeoutError as exc:
            raise RuntimeError("git apply timed out after 60s") from exc
        if result.returncode != 0:
            detail = result.stderr[:400]
            msg = f"git apply failed (rc={result.returncode}): {detail}"
            raise RuntimeError(msg)

    async def _validate_candidate(
        self, worktree: Path, skill_name: str, case_id: str
    ) -> bool:
        """Re-run the corpus runner live INSIDE *worktree* over the regressed
        case + 100% of holdouts + benign sentinels; True iff every non-SKIPPED
        result is PASS.

        Any subprocess/parse failure — or an empty non-SKIPPED set — is a
        conservative False: never ship a candidate we could not prove.
        """
        cases_dir = worktree / _CASES_REL
        case_ids = discover_validation_case_ids(cases_dir, case_id)
        # `sys.executable`, not a bare "python": the loop's PATH may not carry a
        # `python` shim (the runtime venv exposes the interpreter by full path).
        cmd = [
            sys.executable,
            "tests/trust/adversarial/corpus_runner.py",
            "--json",
            "--live-skill",
            skill_name,
            "--cases",
            ",".join(case_ids),
        ]
        try:
            result = await run_subprocess_result(
                *cmd,
                cwd=worktree,
                timeout=_ADVERSARIAL_TIMEOUT_SECONDS,
                extra_env={
                    "HYDRAFLOW_TRUST_ADVERSARIAL_LIVE": "1",
                    "PYTHONPATH": "src:.",
                },
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "refine validation subprocess failed for %s: %s", case_id, exc
            )
            return False
        if result.returncode != 0:
            logger.warning(
                "refine validation exit=%d: %s",
                result.returncode,
                result.stderr[:400],
            )
            return False
        passed = _all_required_pass(result.stdout)
        if not passed:
            logger.warning(
                "refine validation for %s: no all-PASS non-SKIPPED result set "
                "(malformed, empty, all-SKIPPED, or a FAIL present)",
                case_id,
            )
        return passed

    async def _comment_refine_outcome(
        self, case: dict[str, Any], outcome: str, attempts: int
    ) -> None:
        """Note a non-shipping auto-refine outcome on the open drift issue."""
        issue = await self._pr.find_existing_issue(self._drift_title(case))
        if not issue:
            return
        note = _REFINE_OUTCOME_NOTES.get(outcome, outcome)
        await self._pr.post_comment(
            issue,
            f"Auto-refinement did not land (`{outcome}`): {note}. "
            f"Repair attempts so far: {attempts}.",
        )

    def _refine_pr_body(
        self, case: dict[str, Any], skill_name: str, drift_issue: int = 0
    ) -> str:
        module_rel = SKILL_BUILDER_MODULES[skill_name]
        limit_pct = int(PROMPT_LENGTH_DRIFT_LIMIT * 100)
        # Name the provenance: prefer an auto-linking `#N` (from
        # `find_existing_issue`); fall back to the drift-issue title when it
        # couldn't be resolved (0 sentinel). A full per-case validation table
        # is a follow-up (#9724) — one provenance line + the summary suffices.
        provenance = (
            f"#{drift_issue}"
            if drift_issue > 0
            else f'"{self._drift_title(case)}" (search by title)'
        )
        return (
            f"## Automated skill-prompt refinement\n\n"
            f"Corpus case `{case.get('case_id')}` regressed and the "
            f"`{skill_name}` skill stopped catching it. This PR proposes a "
            f"minimal edit to `{module_rel}` that makes the skill catch the case "
            f"again.\n\n"
            f"**Provenance.** Filed in response to skill-prompt drift issue "
            f"{provenance}.\n\n"
            f"**Validation.** The candidate was rebuilt in an ephemeral worktree "
            f"and re-run live against the regressed case, 100% of held-out "
            f"honeypots, and the benign sentinels — every non-skipped case "
            f"PASSed. A ±{limit_pct}% prompt-length tripwire and a builder-only "
            f"path allowlist gated it before validation.\n\n"
            f"_Filed by the `skill_prompt_eval` loop (#9724). Spec §4.6._"
        )

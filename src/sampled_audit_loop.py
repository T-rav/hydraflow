"""Background worker loop — SampledAuditLoop (#10370).

The silent-escape estimator: acceptance sampling applied to the gauntlet. A
read-only ADR-0029 caretaker, **Pattern B like ``EscapeLedgerLoop``** (samples,
audits, records, files findings; NEVER reverts, blocks, or opens fix PRs; and
strictly POST-merge). Where the escape ledger (#10367) counts *detected*
escapes, this loop bounds the *undetected* rate with statistics: a governed
random sample of merged PRs is re-reviewed by a fresh adversarial context, and
the disagreement rate becomes a statistical bound on silent escapes plus a
standing calibration signal for the gates.

Each tick:

1. **Resolve** the merged changes since the last tick (SHA cursor, exactly like
   ``EscapeLedgerLoop`` — prime on first tick with no back-analysis, advance
   unconditionally after a successful tick so a range is sampled at most once).
2. **Sample** — classify each change's blast-radius, then Bernoulli-select at
   the GOVERNED rate (``audit.sampling``), elevated for high-blast-radius
   classes (``audit.stratify``). A per-tick token budget caps the selected set
   (``audit.budget``) — exhaustive re-review is an explicit non-goal.
3. **Audit** — for each sampled change, spawn a fresh adversarial re-review
   (``_AuditLLM``) that sees ONLY the merged diff + linked spec/issue + repo
   state, NEVER the original verdicts. Record ``agree|disagree`` + findings to
   the append-only ``<data_root>/diagnostics/audit_samples.jsonl``.
4. **File findings** — each disagreement files exactly one bounded
   ``hydraflow-find`` issue for the standard adjudication path.
5. **Reconcile** — a filed disagreement whose adjudication closed as UPHELD
   crosses into the escape ledger (``detection_source: sampled-audit``, REUSING
   ``escape.ledger`` — not a fork); a REFUTED one increments the auditor
   false-alarm series.
6. **Govern** — record this tick's disagreement observation and update the
   sample rate by Shewhart's rule (``audit.governance``): widen toward the 20%
   ceiling above the control limit, narrow toward the 2% floor when quiet.

**Surfaces.** The metrics (disagreement rate + Wilson CI, false-alarm rate,
per-gate-class calibration) render on the shared gauntlet-calibration dashboard
panel (``/api/diagnostics/gauntlet-calibration``, reading this loop's
``audit_samples.jsonl`` alongside the judge-independence fail-open ledger). The
committed ``docs/arch/generated/gauntlet-calibration.md`` is a DETERMINISTIC
instrument spec (``arch.generators.gauntlet_calibration``) — the loop writes no
git-committed artifact at runtime, avoiding the factory-on-stale-main drift a
data-bearing generated doc would cause (#10371's decision, adopted here).

**Air-gap seam (config_disable).** ``_AuditLLM`` is a real ``run_lightweight_agent``
spawn. ``sampled_audit_reaudit_enabled`` gates it; the sandbox pins it OFF in
``mockworld.sandbox_main._apply_sandbox_config_overrides`` so the air-gapped
network never sees a real ``claude`` (the exact s51/s56 wedge class). The loop
still ticks/heartbeats + governs; only the spawn is unreachable.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from audit.budget import MAX_DIFF_CONTEXT_CHARS, within_budget
from audit.crosslink import sample_to_escape_record
from audit.detect import (
    current_head_sha,
    diff_for_sha,
    merged_changes_for_range,
)
from audit.disposition import reconcile_disposition
from audit.governance import DEFAULT_BASE_RATE, govern_rate, trim_history
from audit.models import (
    AUDIT_INPUT_SOURCES,
    AuditSample,
    DisagreementObservation,
    MergedChange,
)
from audit.sampling import select_sample
from audit.store import AuditSampleLedger
from audit.stratify import classify_blast_radius
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from escape.ledger import EscapeLedger
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.sampled_audit")

# Hard bound on one adversarial re-audit LLM call (seconds); the LONG_LLM_CYCLE
# watchdog bounds the whole tick.
_AUDIT_LLM_TIMEOUT_S = 300

_ISSUE_LABELS = ["hydraflow-find", "sampled-audit"]

_SAMPLES_FILENAME = "audit_samples.jsonl"
_ESCAPE_LEDGER_FILENAME = "escape_ledger.jsonl"

# How much of the merged diff the auditor is shown (chars) — bounded so a huge
# merge cannot blow the prompt / token budget. Canonical in ``audit.budget`` so
# the truncation window and the budget's diff-token charge stay in lockstep.
_DIFF_CONTEXT_CHARS = MAX_DIFF_CONTEXT_CHARS


class _AuditLLM(Protocol):
    """Minimal one-shot completion seam for the adversarial re-audit.

    Tests inject a fake; production lazily builds :class:`_CLIAuditLLM`.
    """

    async def audit(self, *, prompt: str) -> str: ...


class _CLIAuditLLM:
    """Production auditor: one-shot RAW-text completion via the shared
    lightweight-agent seam (credit-aware, telemetried).

    Never exercised under test; the loop's ``auditor`` kwarg injects a fake for
    all unit + scenario coverage, and the sandbox pins the spawn off entirely.
    """

    def __init__(self, config: HydraFlowConfig, model: str) -> None:
        self._config = config
        self._model = model

    async def audit(self, *, prompt: str) -> str:
        result = await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model=self._model,
            prompt=prompt,
            source="sampled_audit",
            timeout=float(_AUDIT_LLM_TIMEOUT_S),
            issue_labels=(),
        )
        if result.returncode != 0:
            msg = f"audit LLM failed (rc={result.returncode}): {result.stderr[:200]}"
            raise RuntimeError(msg)
        return result.stdout


def build_audit_prompt(change: MergedChange, diff: str) -> str:
    """Assemble the adversarial re-audit prompt — fresh context, NO verdicts.

    Deliberately shows ONLY the merged diff + change metadata (the linked
    spec/issue reference + repo state the auditor may consult). It NEVER echoes
    the original gauntlet verdicts — the fresh-context charter that makes the
    disagreement rate an independent bound (verifiable from the recorded
    ``input_sources`` manifest, which lists exactly these sources).
    """
    return (
        "You are an ADVERSARIAL re-auditor. This change already merged and "
        "passed the gauntlet once. Your charter is to REFUTE it, not rubber-"
        "stamp it: find the reasons this merged change is wrong, unsafe, or "
        "unfaithful to its spec. You have NOT been shown the original review "
        "verdicts — form your own.\n\n"
        f"PR: #{change.pr_number}\n"
        f"Subject: {change.subject}\n"
        f"Merge SHA: {change.merge_sha}\n"
        f"Changed paths ({len(change.changed_paths)}): "
        f"{', '.join(change.changed_paths[:40])}\n\n"
        "Merged diff (truncated):\n"
        f"{diff[:_DIFF_CONTEXT_CHARS]}\n\n"
        'Respond with STRICT JSON: {"verdict": "agree" | "disagree", '
        '"findings": "<one paragraph; empty if agree>"}. "disagree" means you '
        "found a real correctness/safety/spec-fidelity problem the gauntlet "
        "missed — not a stylistic nit."
    )


def parse_audit_response(raw: str) -> tuple[str, str]:
    """Parse ``(verdict, findings)`` from the auditor's raw stdout, tolerantly.

    Accepts a bare JSON object or JSON embedded in prose. Any unparseable /
    unrecognized verdict collapses to ``agree`` with the raw text as findings —
    fail-soft: a malformed auditor response must never be counted as a
    disagreement (which would inflate the headline bound).
    """
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            verdict = str(obj.get("verdict", "agree")).strip().lower()
            findings = str(obj.get("findings", "")).strip()
            if verdict == "disagree":
                return "disagree", findings
            return "agree", findings
    return "agree", text[:500]


class SampledAuditLoop(BaseBackgroundLoop):
    """Governed adversarial re-audit of merged PRs. Read-only (Pattern B).

    Never edits code, never opens a fix PR, never gates. It samples, audits,
    records, and files findings; disagreements go through the standard
    adjudication path and only bookkeeping (ledger rows + cross-links) results.
    """

    # The adversarial re-audit spends LLM calls, so the loop earns the longer
    # per-cycle watchdog bound (#9455 / #9556).
    LONG_LLM_CYCLE = True

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        dedup: DedupStore,
        deps: LoopDeps,
        auditor: _AuditLLM | None = None,
    ) -> None:
        super().__init__(worker_name="sampled_audit", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        self._dedup = dedup
        # Injected fake under test/scenario; production lazily builds _CLIAuditLLM.
        self._auditor = auditor

    def _get_default_interval(self) -> int:
        return self._config.sampled_audit_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: files evidence issues, owns no proposal/acceptance
        # lifecycle to score — HOUSEKEEPING per ADR-0093, mirrors
        # escape_ledger_loop / erosion_metrics_loop.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    # --- paths -----------------------------------------------------------

    @property
    def _samples_path(self) -> Path:
        return self._config.diagnostics_dir / _SAMPLES_FILENAME

    @property
    def _escape_ledger_path(self) -> Path:
        return self._config.diagnostics_dir / _ESCAPE_LEDGER_FILENAME

    # --- main tick -------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.sampled_audit_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        resolved = self._resolve_range()
        if isinstance(resolved, dict):
            # Even with no new commits, reconcile prior pending disagreements so
            # adjudication outcomes (upheld cross-links / refutations) surface on
            # a quiet tick.
            await self._file_findings()
            reconciled = await self._reconcile_pending()
            resolved["reconciled"] = reconciled
            return resolved
        repo_root, commit_range, changes, current_sha = resolved

        rate = self._current_rate()
        audited = await self._sample_and_audit(repo_root, changes, rate)
        filed = await self._file_findings()
        reconciled = await self._reconcile_pending()
        self._govern(audited)

        # Advance the cursor unconditionally: this range has been fully sampled.
        self._state.set_sampled_audit_last_processed_sha(current_sha)

        disagreements = sum(1 for s in audited if s.verdict == "disagree")
        return {
            "status": "ok",
            "range": commit_range,
            "changes": len(changes),
            "sampled": len(audited),
            "disagreements": disagreements,
            "filed": filed,
            "reconciled": reconciled,
            "governed_rate": self._current_rate(),
        }

    def _resolve_range(
        self,
    ) -> tuple[Path, str, list[MergedChange], str] | dict[str, Any]:
        """Resolve the new commit range to sample, or an early-exit status dict.

        Primes the cursor on the first tick ever (no back-analysis); every other
        early exit leaves the cursor untouched so the next tick retries.
        """
        repo_root = Path(self._config.repo_root)
        current = current_head_sha(repo_root)
        if current is None:
            return {"status": "head_sha_unavailable"}

        last = self._state.get_sampled_audit_last_processed_sha()
        if not last:
            self._state.set_sampled_audit_last_processed_sha(current)
            return {"status": "baseline_established", "sha": current}
        if current == last:
            return {"status": "no_new_commits", "sha": current}

        commit_range = f"{last}..{current}"
        changes = merged_changes_for_range(repo_root, commit_range)
        if changes is None:
            return {"status": "changes_unavailable", "range": commit_range}
        return repo_root, commit_range, changes, current

    def _current_rate(self) -> float:
        rate = self._state.get_sampled_audit_governed_rate()
        return rate if rate > 0.0 else DEFAULT_BASE_RATE

    # --- sample + audit --------------------------------------------------

    async def _sample_and_audit(
        self, repo_root: Path, changes: list[MergedChange], rate: float
    ) -> list[AuditSample]:
        """Select a stratified, budget-capped sample and re-audit each. Records rows."""
        rng = random.Random(
            f"{self._worker_name}:{changes[-1].merge_sha if changes else ''}"
        )
        selected = select_sample(changes, base_rate=rate, rng=rng)
        budgeted = within_budget(
            selected, token_budget=int(self._config.sampled_audit_token_budget_per_tick)
        )

        if not self._config.sampled_audit_reaudit_enabled:
            # config_disable sandbox seam: the adversarial re-audit spawn is
            # turned off wholesale on the air-gapped network. The loop still
            # samples-and-ticks; it just records nothing this tick.
            if budgeted:
                logger.info(
                    "SampledAudit: re-audit disabled (config); %d change(s) "
                    "selected but not audited",
                    len(budgeted),
                )
            return []

        ledger = AuditSampleLedger(self._samples_path)
        existing = ledger.existing_ids()
        recorded: list[AuditSample] = []
        for change in budgeted:
            if change.id in existing:
                continue
            sample = await self._audit_one(repo_root, change, rate)
            if sample is None:
                continue
            ledger.append(sample)
            existing.add(change.id)
            recorded.append(sample)
            logger.info(
                "SampledAudit: recorded %s (%s, %s)",
                sample.id,
                sample.blast_radius_class,
                sample.verdict,
            )
        return recorded

    async def _audit_one(
        self, repo_root: Path, change: MergedChange, rate: float
    ) -> AuditSample | None:
        """Run one fresh adversarial re-audit; ``None`` on a soft LLM failure."""
        diff = diff_for_sha(repo_root, change.merge_sha) or ""
        prompt = build_audit_prompt(change, diff)
        model = self._auditor_model()
        try:
            raw = await self._audit(prompt)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "SampledAudit: audit failed for %s", change.id, exc_info=True
            )
            return None
        verdict, findings = parse_audit_response(raw)
        return AuditSample(
            id=change.id,
            audited_at=datetime.now(UTC).isoformat(),
            pr_number=change.pr_number,
            merge_sha=change.merge_sha,
            blast_radius_class=classify_blast_radius(change),
            verdict=verdict,
            findings=findings,
            input_sources=AUDIT_INPUT_SOURCES,
            auditor_model=model,
            sample_rate=rate,
            disposition="pending" if verdict == "disagree" else "n/a",
        )

    async def _audit(self, prompt: str) -> str:
        """Complete *prompt* via the injected fake or a lazily-built CLI client."""
        if self._auditor is None:
            self._auditor = _CLIAuditLLM(self._config, self._auditor_model())
        return await self._auditor.audit(prompt=prompt)

    def _auditor_model(self) -> str:
        """Auditor model — prefer a distinct family (#10371 independence policy).

        Uses the explicit ``sampled_audit_model`` when set (an operator points it
        at a different family from the implementing agent), else falls back to
        the background model / sonnet for a fresh same-family context.
        """
        return (
            self._config.sampled_audit_model
            or self._config.background_model
            or "sonnet"
        )

    # --- finding filing (bounded) ---------------------------------------

    async def _file_findings(self) -> int:
        """File bounded ``hydraflow-find`` issues for pending unfiled disagreements."""
        ledger = AuditSampleLedger(self._samples_path)
        rows = ledger.read_all()
        pending = [
            s
            for s in rows
            if s.verdict == "disagree"
            and s.disposition == "pending"
            and not s.find_issue
        ]
        max_issues = int(self._config.sampled_audit_max_issues_per_tick)
        updated: dict[str, AuditSample] = {}
        filed = 0
        for sample in pending:
            if filed >= max_issues:
                logger.warning(
                    "SampledAudit: per-tick finding cap (%d) reached; remaining "
                    "disagreements deferred to a later tick (finding-rate budget)",
                    max_issues,
                )
                break
            if f"find:{sample.id}" in self._dedup.get():
                continue
            title, body = _render_finding(sample)
            try:
                issue = await self._prs.create_issue(title, body, labels=_ISSUE_LABELS)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "SampledAudit: failed to file finding %s", sample.id, exc_info=True
                )
                continue
            self._dedup.set_all(self._dedup.get() | {f"find:{sample.id}"})
            updated[sample.id] = _with_find_issue(sample, issue)
            filed += 1
            logger.info("SampledAudit: filed finding %s (issue #%s)", sample.id, issue)
        if updated:
            ledger.update_dispositions(updated)
        return filed

    # --- adjudication reconcile -----------------------------------------

    async def _reconcile_pending(self) -> int:
        """Resolve filed disagreements; upheld → escape cross-link, refuted → tally."""
        ledger = AuditSampleLedger(self._samples_path)
        rows = ledger.read_all()
        pending = [
            s
            for s in rows
            if s.verdict == "disagree" and s.disposition == "pending" and s.find_issue
        ]
        if not pending:
            return 0

        escape_ledger = EscapeLedger(self._escape_ledger_path)
        escape_existing = escape_ledger.existing_ids()
        updated: dict[str, AuditSample] = {}
        for sample in pending:
            issue = int(sample.find_issue or 0)
            if issue <= 0:
                continue
            try:
                state = await self._prs.get_issue_state(issue)
                labels = await self._prs.get_issue_labels(issue)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "SampledAudit: reconcile read failed for #%s", issue, exc_info=True
                )
                continue
            disposition = reconcile_disposition(state, labels)
            if disposition == "pending":
                continue
            if disposition == "upheld":
                record = sample_to_escape_record(sample)
                if record.id not in escape_existing:
                    escape_ledger.append(record)
                    escape_existing.add(record.id)
                    logger.info(
                        "SampledAudit: upheld %s → escape ledger %s",
                        sample.id,
                        record.id,
                    )
                updated[sample.id] = sample.with_disposition(
                    "upheld", escape_id=record.id
                )
            else:  # refuted
                updated[sample.id] = sample.with_disposition("refuted")
                logger.info("SampledAudit: %s refuted → auditor false-alarm", sample.id)
        if updated:
            ledger.update_dispositions(updated)
        return len(updated)

    # --- governance ------------------------------------------------------

    def _govern(self, audited: list[AuditSample]) -> None:
        """Record this tick's disagreement observation + update the sample rate.

        Skips a tick that audited NOTHING (Bernoulli selected nothing, the
        budget was exhausted, or the re-audit seam is off): a ``sampled=0``
        observation carries no disagreement signal, yet its ``0.0`` proportion
        is ``<= target`` and would narrow the rate on no information — decaying
        toward the floor on quiet ticks. Governing only on ticks that actually
        sampled keeps the Shewhart series signal-bearing.
        """
        if not audited:
            return
        observation = DisagreementObservation(
            sampled=len(audited),
            disagreements=sum(1 for s in audited if s.verdict == "disagree"),
        )
        history = self._state.get_sampled_audit_disagreement_history()
        series = [DisagreementObservation.from_json_dict(h) for h in history]
        series.append(observation)
        series = trim_history(series)
        new_rate = govern_rate(series, current_rate=self._current_rate())
        self._state.set_sampled_audit_disagreement_history(
            [o.to_json_dict() for o in series]
        )
        self._state.set_sampled_audit_governed_rate(new_rate)


def _with_find_issue(sample: AuditSample, issue: int) -> AuditSample:
    return AuditSample(
        id=sample.id,
        audited_at=sample.audited_at,
        pr_number=sample.pr_number,
        merge_sha=sample.merge_sha,
        blast_radius_class=sample.blast_radius_class,
        verdict=sample.verdict,
        findings=sample.findings,
        input_sources=sample.input_sources,
        auditor_model=sample.auditor_model,
        sample_rate=sample.sample_rate,
        disposition=sample.disposition,
        find_issue=issue or None,
        escape_id=sample.escape_id,
    )


def _render_finding(sample: AuditSample) -> tuple[str, str]:
    """Render (title, body) for a ``hydraflow-find`` issue about one disagreement."""
    title = (
        f"Sampled re-audit disagreement: PR #{sample.pr_number} "
        f"({sample.blast_radius_class}) — adversarial re-review flags a possible "
        "silent escape"
    )
    body = (
        "## Evidence (SampledAuditLoop, automated — #10370)\n\n"
        "A fresh ADVERSARIAL re-audit of this already-merged change (sampled "
        "post-merge, shown only the diff + spec/issue + repo state, NOT the "
        "original verdicts) DISAGREED with the gauntlet.\n\n"
        "| field | value |\n|---|---|\n"
        f"| pr | #{sample.pr_number} |\n"
        f"| merge_sha | `{sample.merge_sha[:12]}` |\n"
        f"| blast_radius_class | {sample.blast_radius_class} |\n"
        f"| audited_at | {sample.audited_at} |\n"
        f"| auditor_model | {sample.auditor_model} |\n\n"
        "### Findings\n\n"
        f"{sample.findings or '(none recorded)'}\n\n"
        "This is a falsification-instrument finding, NOT a gate: the change "
        "already merged. Take the standard adjudication path — fix, refute with "
        "evidence, or encode the exception. Add the `audit-upheld` label when "
        "you confirm/fix a real escape (cross-links into the escape ledger, "
        "`detection_source: sampled-audit`); add the `audit-refuted` label if "
        "the auditor was wrong (counts against its false-alarm budget). A plain "
        "close with NEITHER label stays unadjudicated — an incidental stale/dup "
        "close never fabricates an escape.\n"
    )
    return title, body

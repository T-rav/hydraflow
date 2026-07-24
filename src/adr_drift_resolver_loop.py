"""AdrDriftResolverLoop — triage-before-escalate for ADR-drift rollups (#9976).

``AdrTouchpointAuditorLoop`` (ADR-0056) is a pure DETECTOR: it files one
``hydraflow-adr-drift`` rollup per ADR when a PR's diff touches a `src/`
module the ADR cites, without the ADR's own file in the same diff. It
re-detects the same rollup every tick and, after 3 unresolved attempts,
escalates to a ``hitl-adr-drift-stuck`` HITL issue — never asking "is this
even real?" first. In practice ~70% of drift rollups are false positives (a
caller or co-tenant changed, not the ADR's decision) that need nothing more
than a one-line audit-close.

This loop adds the missing TRIAGE + RESOLVE steps as a SEPARATE caretaker
(ADR-0029). The auditor is never edited by this change and stays exactly
what it was: a pure detector. This loop only READS the auditor's rollup
state (``state.all_adr_rollups()``) and acts on the GitHub issue the
auditor already filed — it never changes ``adr_touchpoint_auditor_loop.py``
or ``adr_drift.py``.

## Pipeline: DETECT → TRIAGE → RESOLVE → FAIL-CLOSED

1. **DETECT** — the auditor already does this. This loop reads
   ``state.all_adr_rollups()`` for open ``ADR-NNNN`` rollups (fleet batches,
   keyed ``FLEET-<pr>``, are skipped — ADR-0056 point 7 makes those
   one-shot, human-closed-only by design; a cross-cutting sweep spanning
   many ADRs at once is exactly the case that deserves a human look, not an
   LLM guess).
2. **TRIAGE** — one LLM call (``adr_drift_triage_llm.AdrDriftTriageLLM``)
   over the ADR's Context+Decision text and the rollup's most-recently-
   contributing PR's diff (scoped to the ADR's cited module(s) via
   ``adr_drift_triage.filter_diff_to_paths``), classifying CONSISTENT /
   REAL_DRIFT / OVER_CITATION / DEAD_CITATION / LOW_CONFIDENCE.
3. **RESOLVE**:
   - CONSISTENT → post a one-line audit comment, close the rollup
     (``reason="not planned"`` — matches the #10025 convention for
     automated non-code closes). No HITL.
   - REAL_DRIFT / OVER_CITATION / DEAD_CITATION → rewrite the rollup's body
     into a concrete ADR-edit brief (which section, what to change), swap
     ``adr_drift_label`` for ``find_label`` on the SAME issue number, and
     post a comment recording the triage classification as the audit
     trail. The relabeled issue now flows through the normal
     discover→plan→implement→review pipeline like any other
     ``hydraflow-find`` issue; when the resulting PR lands the ADR file in
     its diff, the auditor's own ``adrs_resolved_this_tick`` /
     ``_close_and_clear_rollup`` path — driven by state, not labels —
     auto-closes it exactly as it would for any other ADR-file touch. This
     loop does not need to do anything further once relabeled.
   - LOW_CONFIDENCE → add ``hitl_escalation_label`` to the SAME issue and
     post a comment explaining the ambiguity. Rare by design (the prompt
     instructs the model to prefer LOW_CONFIDENCE over a guessed
     CONSISTENT).
4. **FAIL-CLOSED** — a triage call that raises (network/parse/validation
   error) marks NOTHING: no dedup entry is recorded, so the SAME rollup is
   retried next tick rather than silently skipped or defaulted to any
   action. Only an explicit, successfully-parsed ``CONSISTENT`` verdict
   ever closes a rollup; every other outcome (including an error) leaves
   it open.

## Idempotency: one triage per rollup ISSUE, not per rollup ADR

Dedup fingerprint is ``f"{rollup_key}:{issue_number}"`` (both the
``ADR-NNNN`` key AND the specific issue number), not the rollup key alone.
The auditor can close+clear a rollup and later re-file a NEW issue for the
SAME ADR if it drifts again — folding the issue number into the
fingerprint means that new occurrence gets its own fresh triage rather than
being silently skipped forever by a fingerprint left over from the
previous (now-closed) issue. Mirrors ``erosion_metrics_loop.py``'s
fingerprint design note: "a distinct incident... is a new occurrence worth
its own issue", applied here to "worth its own triage".

No new persistent state is added: the dedup store alone is sufficient
because the rollup itself (issue number, contributing PRs) is already
durable in ``state.adr_rollup_issues`` — read via
``StateTracker.all_adr_rollups()`` — and one triage per issue lifetime is
all this loop ever needs to remember.

## Known v1 limitation: same-tick relabel race

If a NEW PR drifts the same ADR again in the auditor's scan window AFTER
this loop has already relabeled the rollup to ``hydraflow-find`` but BEFORE
the ADR file lands, the auditor's own existing-rollup branch
(``_update_drift_rollup``) will still run against that issue number and
overwrite its body back into rollup-evidence shape. The label swap holds
(the auditor's body-update path never touches labels), so the
discover→plan→implement→review handoff this loop made is not undone — only
the body's cosmetic content reverts, until the ADR file itself lands and
the auditor closes the issue. Considered acceptable for v1: the race
requires a second drift-causing PR to land in the same short window, and
even in that case correctness (eventual resolution) is preserved.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from adr_drift_triage import (
    RELABEL_CLASSIFICATIONS,
    DriftClassification,
    filter_diff_to_paths,
)
from adr_drift_triage_llm import AdrDriftTriageLLM, TriageContext
from base_background_loop import BaseBackgroundLoop, LoopDeps
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from adr_drift_triage import TriageVerdict
    from adr_index import ADR, ADRIndex
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.adr_drift_resolver_loop")

_WORKER_NAME = "adr_drift_resolver"


def _adr_num_from_key(rollup_key: str) -> int | None:
    """Parse the ADR number out of an ``ADR-NNNN`` rollup key.

    Returns ``None`` for ``FLEET-<pr>`` keys (skipped — see module
    docstring) or any malformed key, so a corrupt state entry can't crash
    a tick.
    """
    if not rollup_key.startswith("ADR-"):
        return None
    try:
        return int(rollup_key[4:])
    except ValueError:
        return None


def _pr_num_from_fleet_key(rollup_key: str) -> int | None:
    """Parse the PR number out of a ``FLEET-<pr>`` rollup key.

    Returns ``None`` for non-fleet or malformed keys so a corrupt state
    entry can't crash a tick (mirrors ``_adr_num_from_key``).
    """
    if not rollup_key.startswith("FLEET-"):
        return None
    try:
        return int(rollup_key[6:])
    except ValueError:
        return None


def _dedup_key(rollup_key: str, issue_number: int) -> str:
    """Fingerprint for 'already triaged THIS issue instance of this rollup'.

    Folds in ``issue_number`` (not just ``rollup_key``) — see the module
    docstring's "Idempotency" section for why a bare rollup-key fingerprint
    would wrongly suppress triage of a brand new issue filed after the
    previous one closed.
    """
    return f"adr_drift_resolver:{rollup_key}:{issue_number}"


_ADR_FILENAME_RE = re.compile(r"^\d{4}-")


class AdrDriftResolverLoop(BaseBackgroundLoop):
    """Triages open ADR-drift rollups and self-resolves the false positives.

    Sibling of ``AdrTouchpointAuditorLoop`` (ADR-0056) — reads its rollup
    state, acts on its filed issues, never edits its detection code. See
    the module docstring for the full DETECT → TRIAGE → RESOLVE →
    FAIL-CLOSED pipeline.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        adr_index: ADRIndex,
        triage: AdrDriftTriageLLM,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name=_WORKER_NAME, config=config, deps=deps)
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._adr_index = adr_index
        self._triage = triage

    def _get_default_interval(self) -> int:
        return self._config.adr_drift_resolver_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Resolves an EXISTING detection queue (the auditor's rollups)
        # rather than proposing new work of its own — no proposal/
        # acceptance lifecycle to score against a label it originates.
        # HOUSEKEEPING per ADR-0093, mirrors erosion_metrics_loop.py /
        # pr_red_repair_loop.py's own reasoning for the same shape of loop.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    def _find_adr(self, adr_number: int) -> ADR | None:
        for adr in self._adr_index.adrs():
            if adr.number == adr_number:
                return adr
        return None

    def _read_adr_markdown(self, adr_number: int) -> str | None:
        """Read the ADR's own file text, or ``None`` if it can't be found/read.

        ``adr_index.ADR`` only carries a 300-char Context summary — too
        thin for the triage LLM. Globs ``docs/adr/NNNN-*.md`` the same way
        ``adr_drift._adr_file_in_diff`` matches by number prefix (tolerant
        of slug renames), rather than depending on any ADRIndex internal.
        """
        adr_dir = Path(self._config.repo_root) / "docs" / "adr"
        candidates = sorted(
            p
            for p in adr_dir.glob(f"{adr_number:04d}-*.md")
            if _ADR_FILENAME_RE.match(p.name)
        )
        if not candidates:
            return None
        try:
            return candidates[0].read_text(encoding="utf-8")
        except OSError:
            logger.warning(
                "adr_drift_resolver: could not read %s", candidates[0], exc_info=True
            )
            return None

    async def _fetch_scoped_diff(self, pr_number: int, adr: ADR) -> str:
        try:
            diff = await self._pr.get_pr_diff(pr_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "adr_drift_resolver: get_pr_diff(%s) failed", pr_number, exc_info=True
            )
            return ""
        return filter_diff_to_paths(diff, adr.source_files)

    async def _fetch_issue_labels(self, issue_number: int) -> list[str]:
        try:
            return await self._pr.get_issue_labels(issue_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "adr_drift_resolver: get_issue_labels(%s) failed",
                issue_number,
                exc_info=True,
            )
            return []

    def _candidates(self) -> list[tuple[str, int, list[int]]]:
        """Open ``ADR-NNNN`` rollups not yet triaged, as (key, issue#, PRs).

        Skips ``FLEET-<pr>`` keys — those have their own selection method,
        :meth:`_fleet_candidates` — and any rollup already fingerprinted in
        the dedup store for its CURRENT issue number.
        """
        seen = self._dedup.get()
        out: list[tuple[str, int, list[int]]] = []
        for rollup_key, entry in self._state.all_adr_rollups().items():
            if _adr_num_from_key(rollup_key) is None:
                continue
            issue_number = int(entry.get("issue_number", 0))
            if not issue_number:
                continue
            if _dedup_key(rollup_key, issue_number) in seen:
                continue
            pr_numbers = [int(n) for n in entry.get("pr_numbers", [])]
            if not pr_numbers:
                continue
            out.append((rollup_key, issue_number, pr_numbers))
        return out

    def _fleet_candidates(self) -> list[tuple[str, int, int, list[int]]]:
        """Open ``FLEET-<pr>`` rollups not yet triaged, as (key, issue#, pr#,
        member ADR numbers) (#10411).

        Only rollups filed WITH ``adr_numbers`` persisted are triageable — a
        fleet rollup from before this change (or any malformed entry) has no
        member ADRs to triage against and is left exactly as before: one-shot,
        human-closed only.
        """
        seen = self._dedup.get()
        out: list[tuple[str, int, int, list[int]]] = []
        for rollup_key, entry in self._state.all_adr_rollups().items():
            pr_number = _pr_num_from_fleet_key(rollup_key)
            if pr_number is None:
                continue
            issue_number = int(entry.get("issue_number", 0))
            if not issue_number:
                continue
            if _dedup_key(rollup_key, issue_number) in seen:
                continue
            adr_numbers = [int(n) for n in entry.get("adr_numbers", [])]
            if not adr_numbers:
                continue
            out.append((rollup_key, issue_number, pr_number, adr_numbers))
        return out

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.adr_drift_resolver_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        candidates = self._candidates()
        max_per_tick = int(self._config.adr_drift_resolver_max_triage_per_tick)

        triaged = 0
        closed = 0
        relabeled = 0
        escalated = 0
        errors = 0
        skipped = 0

        for rollup_key, issue_number, pr_numbers in candidates:
            if triaged >= max_per_tick:
                break

            adr_number = _adr_num_from_key(rollup_key)
            assert adr_number is not None  # filtered in _candidates()
            adr = self._find_adr(adr_number)
            adr_markdown = self._read_adr_markdown(adr_number)
            if adr is None or adr_markdown is None:
                # No live ADR to triage against (renumbered/deleted since
                # the rollup was filed) — leave for the auditor's own
                # stale-rollup reconcile pass; not this loop's job to guess.
                skipped += 1
                continue

            target_pr = max(pr_numbers)
            pr_diff = await self._fetch_scoped_diff(target_pr, adr)
            issue_labels = await self._fetch_issue_labels(issue_number)

            ctx = TriageContext(
                adr_number=adr.number,
                adr_title=adr.title,
                adr_markdown=adr_markdown,
                pr_number=target_pr,
                pr_diff=pr_diff,
                issue_number=issue_number,
                issue_labels=tuple(issue_labels),
            )
            try:
                verdict = await self._triage.classify(ctx)
            except (AuthenticationError, CreditExhaustedError):
                # Billing/auth signal — propagate to the loop's pause handler
                # (base_background_loop), never swallowed as a benign triage
                # failure. Mirrors term_proposer_loop.py's ``self._llm.draft``
                # error handling: this clause MUST precede the broad
                # (ValueError, RuntimeError) handler below, or the loop keeps
                # spawning triage calls against an exhausted account.
                raise
            except (ValueError, RuntimeError) as exc:
                # A malformed/unparseable LLM response (ValueError from
                # AdrDriftTriageLLM.classify) or a failed spawn (RuntimeError
                # from the runtime adapter) is an expected, recoverable
                # triage-call failure — NOT routed through
                # ``reraise_on_credit_or_bug`` (which treats bare ValueError
                # as a likely code bug and would re-raise it here, wrongly
                # crashing the tick on every malformed model reply). FAIL
                # CLOSED: no dedup entry, so the SAME rollup is retried next
                # tick rather than silently skipped or defaulted to any
                # resolve action.
                logger.warning(
                    "adr_drift_resolver: triage failed for %s issue #%s: %s",
                    rollup_key,
                    issue_number,
                    exc,
                )
                errors += 1
                continue  # FAIL-CLOSED: no dedup entry, retried next tick

            triaged += 1
            if verdict.classification == DriftClassification.CONSISTENT:
                await self._resolve_consistent(issue_number, verdict)
                closed += 1
            elif verdict.classification in RELABEL_CLASSIFICATIONS:
                await self._resolve_relabel(issue_number, adr, verdict)
                relabeled += 1
            else:
                await self._resolve_escalate(issue_number, verdict)
                escalated += 1

            seen = self._dedup.get()
            seen.add(_dedup_key(rollup_key, issue_number))
            self._dedup.set_all(seen)

        fleet_candidates = self._fleet_candidates()
        fleet_triaged = 0
        fleet_closed = 0
        fleet_errors = 0
        fleet_skipped = 0

        for rollup_key, issue_number, pr_number, adr_numbers in fleet_candidates:
            if triaged + fleet_triaged >= max_per_tick:
                break

            outcome = await self._triage_fleet_batch(
                issue_number, pr_number, adr_numbers
            )
            if outcome == "skipped":
                fleet_skipped += 1
                continue
            if outcome == "error":
                fleet_errors += 1
                continue  # FAIL-CLOSED: no dedup entry, retried next tick

            fleet_triaged += 1
            if outcome == "closed":
                fleet_closed += 1

            seen = self._dedup.get()
            seen.add(_dedup_key(rollup_key, issue_number))
            self._dedup.set_all(seen)

        return {
            "status": "ok",
            "candidates": len(candidates),
            "triaged": triaged,
            "closed": closed,
            "relabeled": relabeled,
            "escalated": escalated,
            "errors": errors,
            "skipped": skipped,
            "fleet_candidates": len(fleet_candidates),
            "fleet_triaged": fleet_triaged,
            "fleet_closed": fleet_closed,
            "fleet_errors": fleet_errors,
            "fleet_skipped": fleet_skipped,
        }

    async def _triage_fleet_batch(
        self, issue_number: int, pr_number: int, adr_numbers: list[int]
    ) -> str:
        """Triage every member ADR of one fleet batch against *pr_number*.

        Returns ``'closed' | 'open' | 'skipped' | 'error'``. Fail-closed at
        two levels: a missing member ADR (renumbered/deleted — 'skipped') or
        a triage-call error ('error') leaves the WHOLE batch untriaged, no
        partial resolution and no dedup mark, so it's retried in full next
        tick. All member ADRs are validated to exist BEFORE any triage call
        is spent, so a missing member never wastes an LLM call on the others.
        Once every member triages successfully, the aggregate is 'closed'
        only when ALL members classify CONSISTENT; otherwise 'open' — a
        batched fleet issue stays one-shot/human-closed for any non-clean
        verdict, matching ``AdrTouchpointAuditorLoop``'s existing fleet
        close semantics. Either 'closed' or 'open' is a definitive outcome
        and marks dedup (mirrors the per-ADR ESCALATE branch) — only a call
        ERROR withholds it.
        """
        members: list[tuple[ADR, str]] = []
        for adr_number in adr_numbers:
            adr = self._find_adr(adr_number)
            adr_markdown = self._read_adr_markdown(adr_number)
            if adr is None or adr_markdown is None:
                return "skipped"
            members.append((adr, adr_markdown))

        verdicts: list[TriageVerdict] = []
        issue_labels = await self._fetch_issue_labels(issue_number)
        for adr, adr_markdown in members:
            pr_diff = await self._fetch_scoped_diff(pr_number, adr)
            ctx = TriageContext(
                adr_number=adr.number,
                adr_title=adr.title,
                adr_markdown=adr_markdown,
                pr_number=pr_number,
                pr_diff=pr_diff,
                issue_number=issue_number,
                issue_labels=tuple(issue_labels),
            )
            try:
                verdict = await self._triage.classify(ctx)
            except (AuthenticationError, CreditExhaustedError):
                raise  # billing/auth signal — propagate, see per-ADR comment above
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "adr_drift_resolver: fleet triage failed for issue #%s "
                    "ADR-%04d: %s",
                    issue_number,
                    adr.number,
                    exc,
                )
                return "error"
            verdicts.append(verdict)

        if all(v.classification == DriftClassification.CONSISTENT for v in verdicts):
            adr_numbers_in_order = [adr.number for adr, _ in members]
            await self._resolve_fleet_consistent(
                issue_number, adr_numbers_in_order, verdicts
            )
            return "closed"
        return "open"

    async def _resolve_fleet_consistent(
        self,
        issue_number: int,
        adr_numbers: list[int],
        verdicts: list[TriageVerdict],
    ) -> None:
        """ALL members CONSISTENT: one aggregate audit comment, close, no HITL."""
        lines = [
            "**ADR drift triage: CONSISTENT for all batched ADRs** "
            "(automated, `adr_drift_resolver`)",
            "",
        ]
        for adr_number, verdict in zip(adr_numbers, verdicts, strict=True):
            lines.append(f"- ADR-{adr_number:04d}: {verdict.rationale}")
        lines.extend(
            [
                "",
                "_Closing — none of the batched ADRs' Decision/Context are "
                "contradicted by the cited change. Reopen with evidence if "
                "this is wrong._",
            ]
        )
        await self._pr.post_comment(issue_number, "\n".join(lines))
        await self._pr.close_issue(issue_number, reason="not planned")

    async def _resolve_consistent(
        self, issue_number: int, verdict: TriageVerdict
    ) -> None:
        """CONSISTENT: one-line audit comment, close, no HITL."""
        comment = (
            "**ADR drift triage: CONSISTENT** (automated, "
            "`adr_drift_resolver`)\n\n"
            f"{verdict.rationale}\n\n"
            "_Closing — the cited change does not contradict this ADR's "
            "Decision/Context. Reopen with evidence if this is wrong._"
        )
        await self._pr.post_comment(issue_number, comment)
        await self._pr.close_issue(issue_number, reason="not planned")

    async def _resolve_relabel(
        self, issue_number: int, adr: ADR, verdict: TriageVerdict
    ) -> None:
        """REAL_DRIFT/OVER_CITATION/DEAD_CITATION: relabel to hydraflow-find
        with a concrete ADR-edit brief so the normal pipeline picks it up."""
        section = verdict.section or "Decision"
        body = (
            "## ADR-edit brief (automated triage, `adr_drift_resolver`)\n\n"
            f"**Classification:** `{verdict.classification.value}`\n\n"
            f"**ADR:** ADR-{adr.number:04d}: {adr.title}\n\n"
            f"**Section to edit:** {section}\n\n"
            f"**What to change:** {verdict.rationale}\n\n"
            "This issue was originally filed by `adr_touchpoint_auditor` "
            "(ADR-0056) as a drift rollup and has been triaged and "
            "relabeled `hydraflow-find` so it flows through the normal "
            "discover → plan → implement → review pipeline. Once the "
            f"resulting PR includes `docs/adr/{adr.number:04d}-*.md` in its "
            "diff, the auditor auto-closes this issue on its next tick — no "
            "further action needed here.\n"
        )
        await self._pr.update_issue_body(issue_number, body)
        for label in self._config.adr_drift_label:
            await self._pr.remove_label(issue_number, label)
        await self._pr.add_labels(issue_number, list(self._config.find_label))
        await self._pr.post_comment(
            issue_number,
            f"**ADR drift triage: {verdict.classification.value}** "
            f"(automated, `adr_drift_resolver`)\n\n{verdict.rationale}\n\n"
            "_Relabeled `hydraflow-find` — see the updated issue body for "
            "the ADR-edit brief._",
        )

    async def _resolve_escalate(
        self, issue_number: int, verdict: TriageVerdict
    ) -> None:
        """LOW_CONFIDENCE: flag for human review. Never auto-closed."""
        comment = (
            "**ADR drift triage: LOW_CONFIDENCE** (automated, "
            "`adr_drift_resolver`)\n\n"
            f"{verdict.rationale}\n\n"
            "_The triage model could not confidently classify this finding "
            "from the ADR text + diff evidence. Left open for human review "
            "— not auto-closed or relabeled (fail-closed)._"
        )
        await self._pr.post_comment(issue_number, comment)
        await self._pr.add_labels(
            issue_number, list(self._config.hitl_escalation_label)
        )

"""Early-abort and escalation gates of ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: the decisions that end an attempt *without* spending (or after
refusing to spend) another build — the no-progress abort (#10659/#10616), the
post-build zero-commit route to diagnose (#11568), the per-issue attempt cap,
and the #11457 "resolved elsewhere" gate — plus the HITL/diagnose escalations
each of them fires.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from harness_insights import FailureCategory
from models import EscalationContext, WorkerResult
from phase_utils import issue_state_is_resolved

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import Task, WorkerResultMeta
    from phase_utils import PipelineEscalator
    from ports import PRPort
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementAbortMixin:
    """Early-abort and escalation gates of ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _escalator: PipelineEscalator
    _prs: PRPort
    _state: StateTracker
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        def _transcript_tail(
            self, result: WorkerResult
        ) -> str | None: ...  # provided by _screen

    def _hitl_cause(self, issue: Task, reason: str) -> str:
        """Build a HITL cause string, prefixing with epic context if applicable."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        issue_labels = {t.lower() for t in issue.tags}
        if not (epic_child_labels & issue_labels):
            return reason
        # Try to find parent epic number from issue body
        match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", issue.body)
        if match:
            return f"Epic child (#{match.group(1)}): {reason}"
        return f"Epic child: {reason}"

    def _should_abort_no_progress(self, issue: Task) -> bool:
        """Return ``True`` when *issue* is thrashing and should abort to HITL.

        The signal (#10659/#10616): this attempt is at/over the configured
        ``implement_no_progress_abort_attempts`` threshold AND the immediately
        prior attempt produced no output (zero commits with an error). The
        default threshold equals ``max_issue_attempts`` (3), so the ADR-0063 W5
        corrective retry still runs and only the final, futile build is skipped.
        A threshold of 0 disables the abort entirely.
        """
        threshold = self._config.implement_no_progress_abort_attempts
        if threshold <= 0:
            return False
        attempts = self._state.get_issue_attempts(issue.id)
        # "Prior attempt" means the prior attempt of THIS cycle: a human
        # re-queue resets the counter but not the last worker meta, so attempt
        # 1 with stale zero-commit meta must build, not bounce (#11568).
        if attempts < 2 or attempts < threshold:
            return False
        prior_meta = self._state.get_worker_result_meta(issue.id) or {}
        return self._is_no_output_signal(prior_meta)

    def _should_abort_zero_commit(self, issue: Task) -> bool:
        """Post-build twin of :meth:`_should_abort_no_progress` (#11568).

        ``True`` when THIS attempt's zero-commit result is at/over the
        ``implement_no_progress_abort_attempts`` threshold — default 1, so
        the first zero-commit result routes to diagnose. ``0`` disables both
        aborts (the pre-#11568 retry-to-cap shape).
        """
        threshold = self._config.implement_no_progress_abort_attempts
        if threshold <= 0:
            return False
        # A zero-commit result proves at least one attempt ran, even when the
        # graph was re-entered at ``screen`` without ``decompose`` counting it.
        return max(self._state.get_issue_attempts(issue.id), 1) >= threshold

    @staticmethod
    def _is_no_output_signal(meta: WorkerResultMeta) -> bool:
        """Return ``True`` when *meta* records a no-output failed attempt.

        A no-output attempt committed nothing (``commits == 0``) and carried an
        error. The explicit ``== 0`` (not merely falsy/absent) matters: a prior
        meta without a ``commits`` key — e.g. attempts pre-seeded by a caller
        that never ran a build — is NOT a no-output signal, so the abort never
        fires on a fabricated attempt count.
        """
        return meta.get("commits") == 0 and bool(meta.get("error"))

    async def _escalate_no_progress(self, issue: Task, branch: str) -> WorkerResult:
        """Escalate a non-converging issue to HITL before another build (#10659).

        Posts an abort comment, routes the issue to the diagnose/HITL stage via
        the shared escalator, marks it failed, and returns a terminal
        ``WorkerResult`` — never spending the next (up to ``agent_timeout``)
        build cycle a thrashing issue would otherwise burn.
        """
        attempts = self._state.get_issue_attempts(issue.id)
        prior_meta = self._state.get_worker_result_meta(issue.id) or {}
        last_error = (
            prior_meta.get("error") or "no output (zero commits) on the prior attempt"
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Aborted — No Progress\n\n"
            f"The prior {attempts - 1} implementation attempt(s) produced no "
            "output (zero commits). Rather than spend another full build cycle "
            "re-attempting a non-converging issue, HydraFlow is escalating to "
            "human review now instead of retry-thrashing to the attempt cap "
            "(#10659).\n\n"
            f"Last error: {last_error}\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, "implementation not converging (no commits across attempts)"
            ),
            origin_phase="implement",
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details=(
                f"No-progress early abort after {attempts - 1} no-output "
                f"attempt(s): {last_error}"
            ),
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        self._state.mark_issue(issue.id, "failed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=(
                f"Implementation aborted — no progress across attempts "
                f"({attempts - 1} no-output attempt(s))"
            ),
        )

    async def _escalate_zero_commit(self, issue: Task, result: WorkerResult) -> None:
        """Route a zero-commit attempt to diagnose with the transcript tail (#11568).

        Posts the zero-commit comment (with the tail folded in), stores an
        ``EscalationContext`` whose ``agent_transcript`` IS the tail (the
        diagnostic Stage-1 prompt quotes its head, so the tail is what the
        diagnoser sees), escalates through the shared escalator (label swap
        to diagnose + store transition + harness-failure record) and marks
        the issue failed. The ``WorkerResult`` is left as-is: it is the
        zero-commit result; the routing is the disposition.
        """
        # Floored like ``_should_abort_zero_commit``: a resume at ``screen``
        # can arrive before ``decompose`` counted this attempt.
        attempts = max(self._state.get_issue_attempts(issue.id), 1)
        max_attempts = self._config.max_issue_attempts
        last_error = result.error or "No commits found on branch"
        tail = self._transcript_tail(result)
        logger.warning(
            "Issue #%d: zero commits on attempt %d/%d — routing to diagnose (#11568)",
            issue.id,
            attempts,
            max_attempts,
        )
        tail_section = (
            "\n<details><summary>Transcript tail</summary>\n\n"
            f"```\n{tail}\n```\n</details>\n"
            if tail
            else ""
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — Zero Commits\n\n"
            "The implementation agent ran but produced no commits "
            f"(attempt {attempts}/{max_attempts}). A zero-commit attempt is "
            "not a partial success to retry blindly: rather than spend "
            "another full build on the same shape, HydraFlow is routing this "
            "issue to the diagnostic agent now with the transcript tail "
            "(#11568).\n\n"
            f"Last error: {last_error}\n"
            f"{tail_section}\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, f"implementation produced zero commits (attempt {attempts})"
            ),
            origin_phase="implement",
            agent_transcript=tail,
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details=(
                f"Zero-commit attempt {attempts}/{max_attempts} routed to "
                f"diagnose: {last_error}"
            ),
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        self._state.mark_issue(issue.id, "failed")

    def _build_cap_exceeded_comment(self, attempts: int, last_error: str) -> str:
        """Build the human-readable comment explaining why the cap was exceeded."""
        return (
            f"**Implementation attempt cap exceeded** — "
            f"{attempts - 1} attempt(s) exhausted "
            f"(max {self._config.max_issue_attempts}).\n\n"
            f"Last error: {last_error}\n\n"
            f"Escalating to human review."
        )

    async def _escalate_capped_issue(
        self, issue: Task, attempts: int, last_error: str
    ) -> None:
        """Post the cap comment, escalate to HITL, record harness failure."""
        comment = self._build_cap_exceeded_comment(attempts, last_error)
        await self._transitioner.post_comment(issue.id, comment)
        await self._escalator(
            issue,
            cause=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s)",
            details=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s): {last_error}",
            category=FailureCategory.HITL_ESCALATION,
        )

    async def _check_attempt_cap(self, issue: Task, branch: str) -> WorkerResult | None:
        """Check per-issue attempt cap.  Returns a WorkerResult on cap exceeded, else None."""
        attempts = self._state.increment_issue_attempts(issue.id)
        if attempts <= self._config.max_issue_attempts:
            return None

        last_meta = self._state.get_worker_result_meta(issue.id)
        last_error = (
            last_meta.get("error", "No error details available")
            or "No error details available"
        )
        await self._escalate_capped_issue(issue, attempts, last_error)
        self._state.mark_issue(issue.id, "failed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=f"Implementation attempt cap exceeded ({attempts - 1} attempts)",
        )

    async def _issue_resolved_elsewhere(self, issue_number: int) -> bool:
        """Re-read the issue's state from GitHub; True when resolved (#11457).

        Fail-open by contract: a transient Port failure logs and reads as
        "not resolved" — the gate only ever abandons on a positive resolved
        read, so an unreadable issue still builds (trading a rare duplicate
        PR for a guaranteed stuck factory would be the worse failure).
        Credit/auth exhaustion and likely bugs re-raise per the
        ``reraise_on_credit_or_bug`` dark-factory contract.
        """
        try:
            gh_state = await self._prs.get_issue_state(issue_number)
        except Exception as exc:
            from exception_classify import reraise_on_credit_or_bug

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Issue-state re-check failed for #%d — failing open (build proceeds)",
                issue_number,
                exc_info=True,
            )
            return False
        return issue_state_is_resolved(gh_state)

    async def _abandon_resolved_issue(
        self, issue: Task, branch: str, *, at: str
    ) -> WorkerResult:
        """Abandon an attempt whose issue was resolved elsewhere (#11457).

        Terminal, side-effect-free exit: the build slot returns without an
        agent run, worktree, or PR. Deliberately NO re-enqueue to ready and
        NO label stripping — the issue is closed on GitHub, so
        ``IssueFetcher._is_open`` drops it on the next refresh and
        ``LabelDriftWatcherLoop`` reconciles any stray pipeline labels
        (ADR-0088); re-queueing or swapping here would fight both. The state
        records ``completed`` (the terminal, workspace-clearing status) so no
        retry sweeper can pick a resolved issue back up, and the returned
        ``WorkerResult`` is non-success: this worker delivered nothing.
        """
        logger.info(
            "Issue #%d was resolved elsewhere (closed on GitHub) — abandoning "
            "the attempt at %s before spending further work (#11457)",
            issue.id,
            at,
        )
        self._state.mark_issue(issue.id, "completed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=(
                f"Issue #{issue.id} already resolved elsewhere (closed on "
                f"GitHub) — build abandoned at {at}"
            ),
        )

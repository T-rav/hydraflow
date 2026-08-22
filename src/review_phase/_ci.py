"""Post-merge CI wait-and-fix slice of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: what happens after an approved PR is merged and CI runs — wait
for the checks, dispatch a fix attempt when they go red, escalate the failure
with harness-insight classification, and handle attempt exhaustion.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import review_phase
from harness_insights import FailureCategory
from models import HitlEscalation, PipelineStage

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

    from config import HydraFlowConfig
    from harness_insights import HarnessInsightStore
    from models import CodeScanningAlert, PRInfo, ReviewResult, Task
    from phase_utils import MemorySuggester
    from ports import PRPort
    from reviewer import ReviewRunner
    from state import StateTracker

logger = logging.getLogger("hydraflow.review_phase")


class CiWaitMixin:
    """Post-merge CI wait-and-fix slice of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _harness_insights: HarnessInsightStore | None
    _prs: PRPort
    _reviewers: ReviewRunner
    _state: StateTracker
    _stop_event: asyncio.Event
    _suggest_memory: MemorySuggester

    if TYPE_CHECKING:

        async def _escalate_to_hitl(
            self, esc: HitlEscalation
        ) -> None: ...  # provided by _insights

        async def _publish_review_status(
            self, pr: PRInfo, worker_id: int, status: str
        ) -> None: ...  # provided by _insights

    async def _run_ci_wait_attempt(
        self, pr: PRInfo, attempt: int, worker_id: int
    ) -> tuple[bool, str]:
        """Poll CI once. Return (passed, message)."""
        await self._publish_review_status(pr, worker_id, "ci_wait")
        return await self._prs.wait_for_ci(
            pr.number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

    async def _run_ci_fix_attempt(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        summary: str,
        worker_id: int,
        attempt: int,
        *,
        ci_logs: str = "",
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> bool:
        """Run the CI fix agent. Return True if changes were made and pushed."""
        await self._publish_review_status(pr, worker_id, "ci_fix")
        fix_result = await self._reviewers.fix_ci(
            pr,
            issue,
            wt_path,
            summary,
            attempt=attempt,
            worker_id=worker_id,
            ci_logs=ci_logs,
            code_scanning_alerts=code_scanning_alerts,
        )
        if not fix_result.fixes_made:
            logger.info(
                "CI fix agent made no changes for PR #%d — stopping retries",
                pr.number,
            )
            return False
        await self._prs.push_branch(wt_path, pr.branch)
        return True

    async def _escalate_ci_failure(
        self,
        pr: PRInfo,
        issue: Task,
        logs: str,
        ci_fix_attempts: int,
    ) -> None:
        """Record state, record harness failure, escalate to HITL."""
        self._state.record_ci_fix_rounds(ci_fix_attempts)
        review_phase.record_harness_failure(
            self._harness_insights,
            issue.id,
            FailureCategory.CI_FAILURE,
            f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}",
            pr_number=pr.number,
            stage=PipelineStage.REVIEW,
        )
        cause = f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}"
        # Pre-store richer context with full CI logs before routing to diagnostic loop
        from models import EscalationContext  # noqa: PLC0415

        context = EscalationContext(
            cause=cause,
            origin_phase="review",
            ci_logs=logs,
            pr_number=pr.number,
        )
        self._state.set_escalation_context(issue.id, context)
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=issue.id,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**CI failed** after {ci_fix_attempts} fix attempt(s).\n\n"
                    f"Last failure: {logs}\n\n"
                    f"PR not merged — escalating to human review."
                ),
                event_cause="ci_failed",
                extra_event_data={"ci_fix_attempts": ci_fix_attempts},
                task=issue,
            )
        )

    async def wait_and_fix_ci(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> bool:
        """Wait for CI and attempt fixes if it fails.

        Returns *True* if CI passed and the PR should be merged.
        Mutates *result* to set ``ci_passed`` and ``ci_fix_attempts``.
        """
        max_attempts = self._config.max_ci_fix_attempts
        summary = ""

        for attempt in range(max_attempts + 1):
            passed, summary = await self._run_ci_wait_attempt(pr, attempt, worker_id)
            if passed:
                result.ci_passed = True
                return True

            if attempt >= max_attempts:
                break

            # Fetch full CI logs for observability injection
            ci_logs = ""
            try:
                raw = await self._prs.fetch_ci_failure_logs(pr.number)
                if raw:
                    from log_context import truncate_log  # noqa: PLC0415

                    ci_logs = truncate_log(raw, self._config.max_ci_log_chars)
            except (RuntimeError, OSError):
                logger.debug(
                    "Could not fetch CI failure logs for PR #%d",
                    pr.number,
                    exc_info=True,
                )

            made_changes = await self._run_ci_fix_attempt(
                pr,
                issue,
                wt_path,
                summary,
                worker_id,
                attempt + 1,
                ci_logs=ci_logs,
                code_scanning_alerts=code_scanning_alerts,
            )
            result.ci_fix_attempts += 1
            if not made_changes:
                break

        await self._handle_ci_exhaustion(pr, issue, result, summary, worker_id)
        return False

    async def _handle_ci_exhaustion(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        summary: str,
        worker_id: int,
    ) -> None:
        """Handle the case where all CI fix attempts are exhausted."""
        result.ci_passed = False
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "ci_fix_failure", f"PR #{pr.number}"
            )
        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_ci_failure(pr, issue, summary, result.ci_fix_attempts)

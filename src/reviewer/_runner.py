"""PR review agent runner — launches Claude Code to review and fix PRs."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from review_advisor import ReviewPlan

from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from exception_classify import exc_detail, reraise_on_credit_or_bug
from models import (
    CodeScanningAlert,
    PRInfo,
    ReviewerStatus,
    ReviewResult,
    ReviewUpdatePayload,
    ReviewVerdict,
    Task,
)

from ._context import ReviewContextMixin
from ._fixes import ReviewFixMixin
from ._parsing import ReviewParsingMixin
from ._prompts import ReviewPromptMixin
from ._repo import ReviewRepoMixin

logger = logging.getLogger("hydraflow.reviewer")


class ReviewRunner(
    ReviewContextMixin,
    ReviewFixMixin,
    ReviewParsingMixin,
    ReviewPromptMixin,
    ReviewRepoMixin,
    BaseRunner,
):
    """Launches a ``claude -p`` process to review a pull request.

    The reviewer reads the PR diff, checks code quality and test
    coverage, optionally makes fixes, and returns a verdict.
    """

    _log = logger
    _phase_name: ClassVar[str] = "review"
    PROVIDER_FIELD: ClassVar[str | None] = "review_provider"

    async def review(
        self,
        pr: PRInfo,
        issue: Task,
        worktree_path: Path,
        diff: str,
        worker_id: int = 0,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        bead_tasks: list[dict[str, object]] | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        surface: str = "pr_review",
        human_guidance: str = "",
    ) -> ReviewResult:
        """Run the review agent for *pr*.

        Returns a :class:`ReviewResult` with the verdict and summary.

        ``pre_flight_plan`` is the optional :class:`ReviewPlan` produced by
        ``PreFlightAdvisor`` upstream in :class:`ReviewPhase`. When set, it
        is rendered into the prompt as a focus rubric the executor should
        prioritize during review.

        ``surface`` selects which advisor surface config drives mid-flight
        prompt assembly. Defaults to ``"pr_review"`` for back-compat; Phase
        4 wires other surfaces (``adr_review``, ``visual_gate``, etc.) by
        passing the surface name explicitly.

        ``human_guidance`` (ADR-0099 #4, human-on-the-loop continuous
        steering) is live operator guidance for this issue, sourced by
        :class:`ReviewPhase` from ``StateTracker.get_human_steering``. It
        is folded into the prompt fenced via :func:`fenced_steering_guidance`.
        Empty string when the feature is off or no guidance was posted —
        the fold is then a no-op.
        """
        start = time.monotonic()
        result = ReviewResult(
            pr_number=pr.number,
            issue_number=issue.id,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data=ReviewUpdatePayload(
                    pr=pr.number,
                    issue=issue.id,
                    worker=worker_id,
                    status=ReviewerStatus.REVIEWING.value,
                    role="reviewer",
                ),
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would review PR #%d", pr.number)
            result.verdict = ReviewVerdict.APPROVE
            result.summary = "Dry-run: auto-approved"
            result.success = True
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            precheck_context = await self._run_precheck_context(
                pr, issue, diff, worktree_path
            )
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = await self._build_review_prompt_with_stats(
                pr,
                issue,
                diff,
                precheck_context=precheck_context,
                code_scanning_alerts=code_scanning_alerts,
                bead_tasks=bead_tasks,
                pre_flight_plan=pre_flight_plan,
                surface=surface,
                human_guidance=human_guidance,
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "reviewer"},
                telemetry_stats=prompt_stats,
                issue_labels=issue.tags,
            )
            result.transcript = transcript

            # Parse the verdict from the transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)

            # Gather changes, save transcript, mark success
            await self._record_fix_outcome(
                result,
                worktree_path,
                before_sha,
                transcript,
                transcript_prefix="review-pr",
                label="Review fix",
            )

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.verdict = ReviewVerdict.COMMENT
            detail = exc_detail(exc)
            result.summary = f"Review failed: {detail}"
            logger.error("Review failed for PR #%d: %s", pr.number, detail)

        result.duration_seconds = time.monotonic() - start

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data=ReviewUpdatePayload(
                    pr=pr.number,
                    issue=issue.id,
                    worker=worker_id,
                    status=ReviewerStatus.DONE.value,
                    verdict=result.verdict.value,
                    duration=result.duration_seconds,
                    role="reviewer",
                ),
            )
        )

        return result

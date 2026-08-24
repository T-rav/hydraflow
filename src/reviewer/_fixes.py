"""The two correction flows and their outcome record.

fix_ci and fix_review_findings are siblings: same spawn shape, same recording,
different trigger. _record_fix_outcome is what they share.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from exception_classify import exc_detail, reraise_on_credit_or_bug
from models import (
    CICheckPayload,
    CodeScanningAlert,
    PRInfo,
    ReviewerStatus,
    ReviewResult,
    ReviewUpdatePayload,
    ReviewVerdict,
    Task,
)

logger = logging.getLogger("hydraflow.reviewer")


class ReviewFixMixin(BaseRunner):
    """The two correction flows and their outcome record."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        def _build_ci_fix_prompt(
            self,
            pr: PRInfo,
            issue: Task,
            failure_summary: str,
            attempt: int,
            ci_logs: str = "",
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
        ) -> tuple[str, dict[str, object]]: ...  # provided by _prompts

        def _build_command(
            self, _worktree_path: Path | None = None
        ) -> list[str]: ...  # provided by _prompts

        def _build_review_fix_prompt(
            self,
            pr: PRInfo,
            issue: Task,
            review_summary: str,
            advisor_transcript: str | None = None,
            suggested_fix_direction: str | None = None,
        ) -> str: ...  # provided by _prompts

        def _extract_summary(self, transcript: str) -> str: ...  # provided by _parsing

        async def _get_changed_files(
            self, worktree_path: Path, before_sha: str | None
        ) -> list[str]: ...  # provided by _repo

        async def _get_commit_stat(
            self, worktree_path: Path, before_sha: str | None = None
        ) -> str: ...  # provided by _repo

        async def _get_head_sha(
            self, worktree_path: Path
        ) -> str | None: ...  # provided by _repo

        async def _has_changes(
            self, worktree_path: Path, before_sha: str | None
        ) -> bool: ...  # provided by _repo

        def _parse_verdict(
            self, transcript: str
        ) -> ReviewVerdict: ...  # provided by _parsing

    async def fix_ci(
        self,
        pr: PRInfo,
        issue: Task,
        worktree_path: Path,
        failure_summary: str,
        attempt: int = 1,
        worker_id: int = 0,
        ci_logs: str = "",
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> ReviewResult:
        """Run an agent to fix CI failures.

        Mirrors the :meth:`review` structure: build command, execute,
        parse verdict, check commits.  Returns a :class:`ReviewResult`
        with verdict APPROVE (fixed) or REQUEST_CHANGES (could not fix).
        """
        start = time.monotonic()
        result = ReviewResult(
            pr_number=pr.number,
            issue_number=issue.id,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CI_CHECK,
                data=CICheckPayload(
                    pr=pr.number,
                    issue=issue.id,
                    worker=worker_id,
                    status=ReviewerStatus.FIXING.value,
                    attempt=attempt,
                ),
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would fix CI for PR #%d", pr.number)
            result.verdict = ReviewVerdict.APPROVE
            result.summary = "Dry-run: CI fix skipped"
            result.success = True
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = self._build_ci_fix_prompt(
                pr,
                issue,
                failure_summary,
                attempt,
                ci_logs=ci_logs,
                code_scanning_alerts=code_scanning_alerts,
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
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)
            await self._record_fix_outcome(
                result,
                worktree_path,
                before_sha,
                transcript,
                transcript_prefix="review-pr",
                label="CI fix",
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.verdict = ReviewVerdict.REQUEST_CHANGES
            detail = exc_detail(exc)
            result.summary = f"CI fix failed: {detail}"
            logger.error("CI fix failed for PR #%d: %s", pr.number, detail)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CI_CHECK,
                data=CICheckPayload(
                    pr=pr.number,
                    issue=issue.id,
                    worker=worker_id,
                    status=ReviewerStatus.FIX_DONE.value,
                    attempt=attempt,
                    verdict=result.verdict.value,
                ),
            )
        )

        result.duration_seconds = time.monotonic() - start
        return result

    async def fix_review_findings(
        self,
        pr: PRInfo,
        issue: Task,
        worktree_path: Path,
        review_summary: str,
        worker_id: int = 0,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
    ) -> ReviewResult:
        """Spin up a sub-agent to fix issues found during review.

        Takes the review feedback and asks the agent to fix the identified
        issues, commit the fixes, and report whether it succeeded.

        When invoked from the post-verify advisor's VETO retry loop,
        ``advisor_transcript`` and ``suggested_fix_direction`` carry the
        advisor's disagreement record so the fix prompt can direct the
        executor to address it specifically.
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
                    status=ReviewerStatus.FIXING_REVIEW_FINDINGS.value,
                    role="reviewer",
                ),
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would fix review findings for PR #%d", pr.number)
            result.verdict = ReviewVerdict.APPROVE
            result.summary = "Dry-run: review fix skipped"
            result.success = True
            result.duration_seconds = time.monotonic() - start
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.REVIEW_UPDATE,
                    data=ReviewUpdatePayload(
                        pr=pr.number,
                        issue=issue.id,
                        worker=worker_id,
                        status=ReviewerStatus.FIX_FINDINGS_DONE.value,
                        verdict=result.verdict.value,
                        duration=result.duration_seconds,
                        role="reviewer",
                    ),
                )
            )
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt = self._build_review_fix_prompt(
                pr,
                issue,
                review_summary,
                advisor_transcript=advisor_transcript,
                suggested_fix_direction=suggested_fix_direction,
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "review_fixer"},
                issue_labels=issue.tags,
            )
            result.transcript = transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)
            await self._record_fix_outcome(
                result,
                worktree_path,
                before_sha,
                transcript,
                transcript_prefix="review-fix",
                label="Review-fix",
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.verdict = ReviewVerdict.REQUEST_CHANGES
            detail = exc_detail(exc)
            result.summary = f"Review fix failed: {detail}"
            logger.error("Review fix failed for PR #%d: %s", pr.number, detail)

        result.duration_seconds = time.monotonic() - start

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data=ReviewUpdatePayload(
                    pr=pr.number,
                    issue=issue.id,
                    worker=worker_id,
                    status=ReviewerStatus.FIX_FINDINGS_DONE.value,
                    verdict=result.verdict.value,
                    duration=result.duration_seconds,
                    role="reviewer",
                ),
            )
        )

        return result

    async def _record_fix_outcome(
        self,
        result: ReviewResult,
        worktree_path: Path,
        before_sha: str | None,
        transcript: str,
        *,
        transcript_prefix: str,
        label: str,
    ) -> None:
        """Gather post-execution changes and populate *result* fields.

        Shared by :meth:`review`, :meth:`fix_ci`, and
        :meth:`fix_review_findings` to avoid duplicating the
        change-detection / transcript-saving block.  Also saves the
        transcript to disk via :meth:`~BaseRunner._save_transcript`.
        """
        result.files_changed = await self._get_changed_files(worktree_path, before_sha)
        result.fixes_made = await self._has_changes(worktree_path, before_sha)
        if result.fixes_made:
            if result.files_changed:
                result.commit_stat = await self._get_commit_stat(
                    worktree_path, before_sha
                )
                logger.info(
                    "%s for PR #%d changed files: %s",
                    label,
                    result.pr_number,
                    result.files_changed,
                )
            else:
                logger.warning(
                    "PR #%d: fixes_made is True but no committed file changes detected "
                    "— agent may have left uncommitted changes or the commit was empty",
                    result.pr_number,
                )
        self._save_transcript(transcript_prefix, result.pr_number, transcript)
        result.success = True

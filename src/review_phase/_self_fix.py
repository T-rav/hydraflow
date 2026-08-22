"""Self-fix / re-review loop and merge execution of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: what the phase does when a review comes back REQUEST_CHANGES or
COMMENT — dispatch the executor to fix its own PR, re-review the delta, verify
it, and on approval carry out the merge (including the post-merge conflict
retry).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from models import MergeApprovalContext, ReviewVerdict
from phase_utils import run_with_fatal_guard

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from merge_conflict_resolver import MergeConflictResolver
    from models import (
        CodeScanningAlert,
        HitlEscalation,
        PRInfo,
        ReviewResult,
        Task,
        VisualValidationDecision,
    )
    from ports import PRPort, WorkspacePort
    from post_merge_handler import PostMergeHandler
    from review_advisor import ReviewPlan
    from reviewer import ReviewRunner
    from state import StateTracker

logger = logging.getLogger("hydraflow.review_phase")


class SelfFixMixin:
    """Self-fix / re-review loop and merge execution of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan]
    _config: HydraFlowConfig
    _conflict_resolver: MergeConflictResolver
    _post_merge: PostMergeHandler
    _prs: PRPort
    _reviewers: ReviewRunner
    _state: StateTracker
    _workspaces: WorkspacePort

    if TYPE_CHECKING:

        async def _escalate_to_hitl(
            self, esc: HitlEscalation
        ) -> None: ...  # provided by _insights

        async def _publish_review_status(
            self, pr: PRInfo, worker_id: int, status: str
        ) -> None: ...  # provided by _insights

        async def check_visual_gate(
            self,
            pr: PRInfo,
            issue: Task,
            result: ReviewResult,
            worker_id: int,
        ) -> bool: ...  # provided by _visual_gate

        async def wait_and_fix_ci(
            self,
            pr: PRInfo,
            issue: Task,
            wt_path: Path,
            result: ReviewResult,
            worker_id: int,
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
        ) -> bool: ...  # provided by _ci

    async def _handle_self_fix_re_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str]:
        """Re-review a PR after the reviewer self-fixed findings.

        Returns ``(updated_result, updated_diff)``.  If the re-review
        approves, the upgraded result and refreshed diff are returned.
        On failure or continued rejection the original result is preserved.

        ``surface`` selects which advisor surface config drives the
        executor's mid-flight prompt assembly on the re-review. Defaults to
        ``"pr_review"`` for back-compat (T30.5 I2: thread surface through
        retry-path re-reviews so future multi-surface retry loops route to
        the correct surface config rather than silently defaulting).
        """
        logger.info(
            "PR #%d: reviewer self-fixed with %s verdict — re-reviewing updated code",
            pr.number,
            result.verdict.value,
        )

        async def _re_review() -> tuple[ReviewResult, str]:
            await self._publish_review_status(pr, worker_id, "re_reviewing")
            updated_diff = await self._prs.get_pr_diff(pr.number)
            # Thread the pre-flight plan into retries so the executor keeps
            # the same focus rubric across the loop (T24.5 closed I3).
            # Human-on-the-loop continuous steering (ADR-0099 #4): re-fetch
            # guidance so a `/steer` posted mid-retry-loop reaches the
            # re-review prompt too.
            human_guidance = (
                self._state.get_human_steering(str(issue.id)).guidance or ""
            )
            re_result = await self._reviewers.review(
                pr,
                issue,
                wt_path,
                updated_diff,
                worker_id=worker_id,
                code_scanning_alerts=code_scanning_alerts,
                pre_flight_plan=self._advisor_pre_flight_plan.get((surface, pr.number)),
                surface=surface,
                human_guidance=human_guidance,
            )
            if re_result.fixes_made:
                await self._prs.push_branch(wt_path, pr.branch)
            if re_result.verdict == ReviewVerdict.APPROVE:
                logger.info(
                    "PR #%d: self-fix re-review passed — upgrading verdict to APPROVE",
                    pr.number,
                )
                return re_result, updated_diff
            logger.info(
                "PR #%d: self-fix re-review still returned %s — proceeding with rejection",
                pr.number,
                re_result.verdict.value,
            )
            return result, updated_diff

        return await run_with_fatal_guard(
            _re_review(),
            on_failure=lambda _: (result, diff),
            context=f"PR #{pr.number}: self-fix re-review failed — falling back to original rejection",
            log=logger,
        )

    async def _run_single_review_fix(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        attempt: int,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str] | None:
        """Run one fix-then-re-review cycle.

        Returns ``(re_result, updated_diff)`` on success, or ``None`` if
        the fix agent made no changes.

        ``advisor_transcript`` and ``suggested_fix_direction`` are
        propagated into the fix-agent prompt when the call originates from
        the post-verify advisor's VETO retry loop.

        ``surface`` selects which advisor surface config drives the
        re-review's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T30.5 I2).
        """
        await self._publish_review_status(pr, worker_id, "fixing_review")

        fix_result = await self._reviewers.fix_review_findings(
            pr,
            task,
            wt_path,
            result.summary,
            worker_id=worker_id,
            advisor_transcript=advisor_transcript,
            suggested_fix_direction=suggested_fix_direction,
        )

        if not fix_result.fixes_made:
            logger.info(
                "PR #%d: fix agent made no changes on attempt %d — giving up",
                pr.number,
                attempt,
            )
            return None

        # Push the fixes
        await self._prs.push_branch(wt_path, pr.branch)

        # Re-review
        await self._publish_review_status(pr, worker_id, "re_reviewing")
        updated_diff = await self._prs.get_pr_diff(pr.number)
        # Thread the pre-flight plan into retries so the executor keeps
        # the same focus rubric across the loop (T24.5 closed I3).
        # Human-on-the-loop continuous steering (ADR-0099 #4): re-fetch
        # guidance so a `/steer` posted mid-fix-loop reaches the re-review
        # prompt too.
        human_guidance = self._state.get_human_steering(str(task.id)).guidance or ""
        re_result = await self._reviewers.review(
            pr,
            task,
            wt_path,
            updated_diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            pre_flight_plan=self._advisor_pre_flight_plan.get((surface, pr.number)),
            surface=surface,
            human_guidance=human_guidance,
        )

        if re_result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        return re_result, updated_diff

    async def _attempt_review_fix(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
        surface: str = "pr_review",
    ) -> tuple[ReviewResult, str]:
        """Spin up a sub-agent to fix review findings, then re-review.

        Tries up to 2 fix-then-review cycles. If the fix agent makes
        changes and the re-review approves, returns the upgraded result.
        Otherwise falls through to the normal rejection path.

        When called from the post-verify advisor's VETO retry loop,
        ``advisor_transcript`` and ``suggested_fix_direction`` thread the
        full advisor disagreement record into the executor's prompt so the
        next attempt can directly address the disagreement.

        ``surface`` selects which advisor surface config drives the
        re-review's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T30.5 I2).
        """
        max_fix_attempts = 2

        for attempt in range(1, max_fix_attempts + 1):
            logger.info(
                "PR #%d: attempting review fix %d/%d",
                pr.number,
                attempt,
                max_fix_attempts,
            )

            attempt_outcome = await run_with_fatal_guard(
                self._run_single_review_fix(
                    pr,
                    task,
                    wt_path,
                    result,
                    attempt,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                    advisor_transcript=advisor_transcript,
                    suggested_fix_direction=suggested_fix_direction,
                    surface=surface,
                ),
                on_failure=lambda _: None,
                context=f"PR #{pr.number}: review fix attempt {attempt} failed — falling back to rejection",
                log=logger,
            )

            if attempt_outcome is None:
                break

            re_result, updated_diff = attempt_outcome

            if re_result.verdict == ReviewVerdict.APPROVE:
                logger.info(
                    "PR #%d: review fix attempt %d succeeded — upgrading to APPROVE",
                    pr.number,
                    attempt,
                )
                return re_result, updated_diff

            # Still rejected — use the new feedback for the next attempt
            logger.info(
                "PR #%d: review fix attempt %d still %s — %s",
                pr.number,
                attempt,
                re_result.verdict.value,
                "retrying" if attempt < max_fix_attempts else "falling through",
            )
            result = re_result
            diff = updated_diff

        return result, diff

    async def _run_delta_verification(self, pr: PRInfo, diff: str) -> str:
        """Run delta verification comparing plan's File Delta section to actual diff.

        Returns a summary string (empty if no plan or no delta section).
        """
        from delta_verifier import parse_file_delta, verify_delta

        plan_path = self._config.plans_dir / f"issue-{pr.issue_number}.md"
        if not plan_path.exists():
            return ""

        try:
            plan_text = plan_path.read_text()
        except OSError:
            return ""

        planned_files = parse_file_delta(plan_text)
        if not planned_files:
            return ""

        # Extract actual changed files from the diff
        actual_files = await self._prs.get_pr_diff_names(pr.number)
        report = verify_delta(planned_files, actual_files)

        if report.has_drift:
            summary = report.format_summary()
            logger.warning(
                "Delta drift for PR #%d (issue #%d): %d missing, %d unexpected",
                pr.number,
                pr.issue_number,
                len(report.missing),
                len(report.unexpected),
            )
            return summary
        return ""

    async def _handle_approved_merge(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        visual_decision: VisualValidationDecision | None = None,
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate)."""
        ctx = MergeApprovalContext(
            pr=pr,
            issue=issue,
            result=result,
            diff=diff,
            worker_id=worker_id,
            ci_gate_fn=self.wait_and_fix_ci,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
            code_scanning_alerts=code_scanning_alerts,
            visual_gate_fn=self.check_visual_gate,
            visual_decision=visual_decision,
            merge_conflict_fix_fn=self._attempt_post_merge_conflict_fix,
        )
        await self._post_merge.handle_approved(ctx)

    async def _attempt_post_merge_conflict_fix(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
    ) -> bool:
        """Attempt conflict resolution after a failed GitHub merge.

        This keeps the standard review path aligned with unsticker behavior:
        resolve merge conflicts on the branch, push updates, then retry merge.
        """
        wt_path = self._config.workspace_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._workspaces.create(pr.issue_number, pr.branch)

        resolution = await self._conflict_resolver.resolve_merge_conflicts(
            pr,
            issue,
            wt_path,
            worker_id=worker_id,
            source="post_merge",
        )
        if not resolution.success:
            return False

        if resolution.used_rebuild:
            await self._prs.push_branch(
                self._config.workspace_path_for_issue(pr.issue_number),
                pr.branch,
                force=True,
            )
        else:
            await self._prs.push_branch(wt_path, pr.branch)
        return True

"""Cause -> fix: the dispatch and the non-timeout repair paths.

``_resolve_by_cause`` is the switch; ``_resolve_ci_or_quality`` drives an
agent against a failing check and ``_resolve_generic`` is the fallback for
a cause nobody has taught the unsticker to read yet.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug
from models import ConflictResolutionResult, PRInfo

from ._causes import FailureCause

if TYPE_CHECKING:
    from agent import AgentRunner
    from hitl_runner import HITLRunner
    from merge_conflict_resolver import MergeConflictResolver
    from models import GitHubIssue
    from phase_utils import MemorySuggester
    from ports import WorkspacePort
    from state import StateTracker


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnstickerResolveMixin:
    """Cause -> fix: the dispatch and the non-timeout repair paths."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _hitl_runner: HITLRunner | None
    _resolver: MergeConflictResolver | None
    _state: StateTracker
    _suggest_memory: MemorySuggester
    _workspaces: WorkspacePort

    if TYPE_CHECKING:

        def _build_ci_fix_prompt(
            self, issue: GitHubIssue, pr_url: str, cause: str
        ) -> tuple[str, dict[str, object]]: ...  # provided by _prompts

        async def _resolve_ci_timeout(
            self,
            issue_number: int,
            issue: GitHubIssue,
            wt_path: Path,
            branch: str,
            pr_url: str,
            pr_number: int = 0,
        ) -> bool: ...  # provided by _timeout

    async def _resolve_by_cause(
        self,
        cause: FailureCause,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> ConflictResolutionResult:
        """Dispatch to the appropriate resolver based on cause classification.

        Returns a :class:`ConflictResolutionResult` — *used_rebuild* is True
        when the fresh-branch rebuild path was taken (caller should force-push).
        """
        if cause == FailureCause.MERGE_CONFLICT:
            if self._resolver is None:
                logger.error(
                    "#%d: no resolver configured, cannot resolve conflict",
                    issue_number,
                )
                return ConflictResolutionResult(success=False, used_rebuild=False)
            pr = PRInfo(
                number=pr_number,
                issue_number=issue_number,
                branch=branch,
                url=pr_url,
            )
            return await self._resolver.resolve_merge_conflicts(
                pr, issue.to_task(), wt_path, worker_id=None, source="pr_unsticker"
            )
        if cause == FailureCause.CI_TIMEOUT:
            success = await self._resolve_ci_timeout(
                issue_number,
                issue,
                wt_path,
                branch,
                pr_url=pr_url,
                pr_number=pr_number,
            )
            return ConflictResolutionResult(success=success, used_rebuild=False)
        if cause in (FailureCause.CI_FAILURE, FailureCause.REVIEW_FIX_CAP):
            success = await self._resolve_ci_or_quality(
                issue_number,
                issue,
                wt_path,
                branch,
                pr_url=pr_url,
                pr_number=pr_number,
            )
            return ConflictResolutionResult(success=success, used_rebuild=False)
        success = await self._resolve_generic(issue_number, issue, wt_path, branch)
        return ConflictResolutionResult(success=success, used_rebuild=False)

    async def _resolve_ci_or_quality(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> bool:
        """Rebase on main and run agent with a CI/quality fix prompt."""
        # First rebase on main
        clean = await self._workspaces.start_merge_main(wt_path, branch)
        if not clean:
            # If there are conflicts during rebase, try to resolve them first
            await self._workspaces.abort_merge(wt_path)

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        prompt, prompt_stats = self._build_ci_fix_prompt(issue, pr_url, cause_str)

        try:
            cmd = self._agents.build_command(wt_path)
            transcript = await self._agents.execute(
                cmd,
                prompt,
                wt_path,
                {"issue": issue_number, "source": "pr_unsticker"},
                issue_labels=issue.labels,
                telemetry_stats=prompt_stats,
            )
            if self._resolver is not None:
                self._resolver.save_conflict_transcript(
                    pr_number, issue_number, 1, transcript, source="unsticker"
                )
            else:
                logger.warning(
                    "No resolver configured; CI fix transcript for issue #%d not saved",
                    issue_number,
                )

            await self._suggest_memory(
                transcript, "pr_unsticker", f"issue #{issue_number}"
            )

            verify = await self._agents.verify_result(wt_path, branch)
            if verify.passed:
                return True

            logger.warning(
                "CI/quality fix failed for issue #%d: %s",
                issue_number,
                verify.summary[:200] if verify.summary else "",
            )
            return False
        except (OSError, RuntimeError, ValueError, asyncio.CancelledError) as exc:
            # CreditExhaustedError subclasses RuntimeError — reraise it (plus
            # auth/likely-bug) instead of soft-failing the CI fix attempt.
            reraise_on_credit_or_bug(exc)
            logger.error(
                "Unsticker CI fix agent failed for issue #%d: %s",
                issue_number,
                exc,
            )
            return False

    async def _resolve_generic(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
    ) -> bool:
        """Use HITLRunner for generic/unknown causes."""
        if self._hitl_runner is None:
            logger.warning(
                "No HITL runner available for generic fix on issue #%d",
                issue_number,
            )
            return False

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        correction = f"Automated fix attempt by PR Unsticker. Cause: {cause_str}"

        result = await self._hitl_runner.run(
            issue=issue,
            correction=correction,
            cause=cause_str,
            worktree_path=wt_path,
        )
        return result.success

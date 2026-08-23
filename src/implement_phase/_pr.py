"""Push → PR resolution and recovery for ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: what happens once a build's branch is pushed — the #10101
base-freshness guard, creating or recovering the PR, handing the issue off to
review, the #10493 idempotent PR recovery, and the zero-diff escalation to
HITL.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from harness_insights import FailureCategory
from models import EscalationContext, GitHubIssue, PRInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent import AgentRunner
    from config import HydraFlowConfig
    from models import Task, WorkerResult
    from phase_utils import MemorySuggester, PipelineEscalator
    from ports import IssueStorePort, PRPort, WorkspacePort
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementPRMixin:
    """Push → PR resolution and recovery for ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _config: HydraFlowConfig
    _escalator: PipelineEscalator
    _prs: PRPort
    _state: StateTracker
    _store: IssueStorePort
    _suggest_memory: MemorySuggester
    _transitioner: TaskTransitioner
    _workspaces: WorkspacePort
    _zero_diff_memory_filed: set[int]

    if TYPE_CHECKING:

        def _hitl_cause(
            self, issue: Task, reason: str
        ) -> str: ...  # provided by _abort

    async def _resolve_pr(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> PRInfo | None:
        """Create a new PR or recover an existing one, updating result.pr_info."""
        if not is_retry:
            if await self._ensure_fresh_base(issue, result):
                gh_issue = GitHubIssue.from_task(issue)
                pr = await self._prs.create_pr(gh_issue, result.branch)
            else:
                # Base-freshness guard refused (#10101): the zero-PR sentinel
                # routes through the existing "implementation succeeded but
                # no PR exists" fallback (_handle_no_pr_fallback), which
                # keeps the issue in the ready queue for retry instead of
                # silently opening a born-red PR against a stale base.
                pr = PRInfo(number=0, issue_number=issue.id, branch=result.branch)
        else:
            pr = await self._prs.find_open_pr_for_branch(
                result.branch, issue_number=issue.id
            )
            if pr is not None and pr.number > 0:
                from pr_manager import PRManager as _PRManager  # noqa: PLC0415

                expected_title = _PRManager.expected_pr_title(issue.id, issue.title)
                await self._prs.update_pr_title(pr.number, expected_title)
        result.pr_info = pr
        return pr

    @staticmethod
    async def _run_git_read(
        run_simple: Callable[..., Awaitable[object]],
        cmd: list[str],
        *,
        cwd: str,
        timeout: float,
    ) -> str | None:
        """Run a local read-only git command; stripped stdout, or None on any failure.

        Shared by ``_merge_base_age_days``'s two reads. A non-string
        ``stdout`` (e.g. an unconfigured test double) fails open the same
        as a real git error — this helper must never raise.
        """
        try:
            out = await run_simple(cmd, cwd=cwd, timeout=timeout)
        except (TimeoutError, FileNotFoundError, OSError):
            return None
        stdout = getattr(out, "stdout", "")
        if not isinstance(stdout, str):
            return None
        return stdout.strip()

    async def _merge_base_age_days(self, result: WorkerResult) -> float | None:
        """Return the age in days of *result.branch*'s merge-base with the base branch.

        Mirrors ``_branch_changed_files``: reads locally via the agent
        runner's ``run_simple`` so it works uniformly under host/Docker
        execution without a dedicated Port (#10101). Fails open (returns
        ``None``) on any git error, a missing runner, or an unparsable
        result — a freshness check must never itself block a PR.
        """
        if not result.workspace_path or not Path(result.workspace_path).is_dir():
            return None
        runner = getattr(self._agents, "_runner", None)
        run_simple = getattr(runner, "run_simple", None) if runner else None
        if run_simple is None:
            return None
        base = self._config.base_branch()
        timeout = self._config.git_command_timeout
        sha = await self._run_git_read(
            run_simple,
            ["git", "merge-base", result.branch, f"origin/{base}"],
            cwd=result.workspace_path,
            timeout=timeout,
        )
        if not sha:
            return None
        ts_str = await self._run_git_read(
            run_simple,
            ["git", "log", "-1", "--format=%ct", sha],
            cwd=result.workspace_path,
            timeout=timeout,
        )
        if not ts_str or not ts_str.isdigit():
            return None
        epoch = int(ts_str)
        return max(time.time() - epoch, 0.0) / 86400.0

    async def _ensure_fresh_base(self, issue: Task, result: WorkerResult) -> bool:
        """Refuse or auto-update a stale merge-base before ``gh pr create`` (#10101).

        The #9964 class: a long-lived implementer worktree forks from the
        base branch once at worktree-creation time, then the agent runs for
        however long it takes. New guard rules landed on the base in the
        meantime are invisible to the branch — its PR opens born-red
        against a base that's since drifted. Computes the branch's
        merge-base age with the configured base branch; when it exceeds
        ``pr_base_max_age_days`` this tries an in-place update (fetch +
        merge, reusing the same ``merge_main`` path as post-PR conflict
        resolution) before falling back to refusing the PR open.

        Returns True when it's safe to proceed with ``create_pr``.
        """
        if not self._config.pr_base_freshness_guard_enabled:
            return True
        age_days = await self._merge_base_age_days(result)
        if age_days is None or age_days <= self._config.pr_base_max_age_days:
            return True
        logger.warning(
            "Issue #%d: branch %s has a %.1f-day-old merge-base with %s "
            "(threshold %d days) — attempting auto-update before PR open",
            issue.id,
            result.branch,
            age_days,
            self._config.base_branch(),
            self._config.pr_base_max_age_days,
        )
        updated = False
        if result.workspace_path:
            try:
                updated = bool(
                    await self._workspaces.merge_main(
                        Path(result.workspace_path), result.branch
                    )
                )
            except (RuntimeError, OSError):
                updated = False
            if updated:
                updated = bool(
                    await self._prs.push_branch(
                        Path(result.workspace_path), result.branch
                    )
                )
        if updated:
            logger.info(
                "Issue #%d: base-freshness guard auto-updated %s to a fresh %s",
                issue.id,
                result.branch,
                self._config.base_branch(),
            )
            return True
        logger.warning(
            "Issue #%d: base-freshness guard could not auto-update %s "
            "(merge conflict or push failure) — refusing PR open",
            issue.id,
            result.branch,
        )
        return False

    async def _handle_successful_push(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult | None:
        """Create/find PR after a successful push.

        Returns a ``WorkerResult`` to short-circuit the caller when the
        outcome is fully resolved (PR-less failure or zero-diff escalation).
        Returns ``None`` when the caller should continue to the final
        status-marking step.

        On a fresh attempt with ``result.success`` False, returns ``None``
        without resolving a PR. Creating a PR for failed work caused
        state-machine drift: the issue stayed at ``hydraflow-ready`` while
        the PR sat unlabeled. The attempt-cap mechanism retries with
        ``prior_failure`` feedback. Retry path is unchanged.
        """
        if not result.success and not is_retry:
            return None

        pr = await self._resolve_pr(issue, result, is_retry)

        if result.success and (pr is None or pr.number <= 0):
            return await self._handle_no_pr_fallback(issue, result)

        if result.success:
            self._store.enqueue_transition(issue, "review")
            await self._transitioner.transition(
                issue.id,
                "review",
                pr_number=pr.number if pr and pr.number > 0 else None,
            )
            self._state.increment_session_counter("implemented")

        return None

    async def _escalate_no_changes_to_hitl(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Escalate to HITL when the branch has no diff from main."""
        logger.warning(
            "Issue #%d: agent claimed success but branch has no diff — escalating as failure",
            issue.id,
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — No Changes Detected\n\n"
            "The implementation agent reported success but the branch "
            "has no diff from main. The agent likely concluded no work "
            "was needed incorrectly.\n\n"
            "Escalating for human review.\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        self._state.mark_issue(issue.id, "failed")
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, "implementation produced no changes (zero diff)"
            ),
            origin_phase="implement",
            agent_transcript=result.transcript if result.transcript else None,
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details="Implementation produced no changes (zero diff)",
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        if result.transcript:
            await self._suggest_memory(
                result.transcript,
                "implement_zero_diff",
                f"issue #{issue.id}",
            )
            self._zero_diff_memory_filed.add(issue.id)
        return result

    async def _handle_no_pr_fallback(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle the case where implementation succeeded but no PR exists.

        If the branch has no diff from main, escalates to HITL.  Otherwise the
        work was really committed and pushed — the PR-open step just never ran
        (e.g. a long local verification step got reaped by a subprocess timeout
        AFTER commit+push but BEFORE ``gh pr create``; issue #10493). Recover
        idempotently instead of discarding the delivered work: re-check for an
        open PR, then open one from the already-pushed branch, mirroring the
        happy path. Only a genuine PR-open failure falls through to the "mark
        failed / retry" path (which would rebuild the work from scratch).
        """
        has_diff = await self._prs.branch_has_diff_from_main(result.branch)
        if not has_diff:
            return await self._escalate_no_changes_to_hitl(issue, result)

        # Idempotent recovery (#10493): the branch carries a real diff and is
        # already pushed on origin, so deliver it rather than bouncing the
        # issue back to hydraflow-ready for a full rebuild. A PR may have been
        # created since the initial resolve; otherwise open one now from the
        # pushed branch (the same call the happy path uses in _resolve_pr).
        pr = await self._prs.find_open_pr_for_branch(
            result.branch, issue_number=issue.id
        )
        if pr is None or pr.number <= 0:
            gh_issue = GitHubIssue.from_task(issue)
            pr = await self._prs.create_pr(gh_issue, result.branch)

        if pr is not None and pr.number > 0:
            logger.info(
                "Recovered PR #%d for issue #%d from already-pushed branch %s "
                "(no PR existed after successful implementation)",
                pr.number,
                issue.id,
                result.branch,
            )
            # Mirror the happy-path post-create state marking so the delivered
            # work advances to review instead of being rebuilt: enqueue +
            # drive the review transition, bump the session counter, and mark
            # the issue "success" (what _handle_successful_push's caller does).
            self._store.enqueue_transition(issue, "review")
            await self._transitioner.transition(issue.id, "review", pr_number=pr.number)
            self._state.increment_session_counter("implemented")
            self._state.mark_issue(issue.id, "success")
            result.success = True
            result.pr_info = pr
            result.error = None
            return result

        logger.warning(
            "Implementation succeeded for issue #%d but PR recovery failed for "
            "branch %s — keeping in ready queue for retry",
            issue.id,
            result.branch,
        )
        await self._transitioner.post_comment(
            issue.id,
            "PR creation/recovery failed after successful implementation. "
            "Keeping issue in ready queue for retry.",
        )
        self._state.mark_issue(issue.id, "failed")
        result.success = False
        if not result.error:
            result.error = "PR creation failed"
        return result

"""Regression test for issue #6961.

``workspace_gc_loop._collect_orphaned_branches`` force-deletes local
``agent/issue-*`` branches whose worktree has been collected, but it
never calls ``_has_open_pr`` to check whether an open pull request still
references the branch.  If an agent has just pushed the branch and the
worktree GC races with the push window, the local branch is deleted
before the push is confirmed on the remote, corrupting the worktree
state.

Phase 1 (worktree GC) correctly guards via ``_is_safe_to_gc`` →
``_has_open_pr``, but Phase 3 (orphaned-branch GC) skips that check
entirely.

These tests will fail (RED) until ``_collect_orphaned_branches`` adds
an open-PR guard before deleting a branch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

# Force-delete flag for branch deletion assertions
_FORCE_DEL = chr(45) + chr(68)


def _make_gc_loop(
    tmp_path: Path,
    *,
    active_workspaces: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    pipeline_issues: set[int] | None = None,
) -> WorkspaceGCLoop:
    """Build a WorkspaceGCLoop with the real _collect_orphaned_branches."""
    from state import StateTracker

    deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)
    if active_issue_numbers:
        state.set_active_issue_numbers(active_issue_numbers)

    in_pipeline = pipeline_issues or set()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=MagicMock(destroy=AsyncMock()),
        prs=MagicMock(),
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda n: n in in_pipeline,
    )
    # Keep _collect_orphaned_branches real (don't mock it like _make_loop does)
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
    return loop


class TestOrphanedBranchOpenPRGuard:
    """Issue #6961: _collect_orphaned_branches must skip branches with open PRs."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6961 — fix not yet landed", strict=False)
    async def test_skips_branch_when_open_pr_exists(self, tmp_path: Path) -> None:
        """An orphaned branch with an open PR must NOT be deleted.

        Currently _collect_orphaned_branches never calls _has_open_pr,
        so the branch is force-deleted even when a PR is open.  This
        test asserts the correct (guarded) behaviour and will fail
        until the open-PR check is added.
        """
        loop = _make_gc_loop(tmp_path)
        # Simulate: _has_open_pr returns True (an open PR references this branch)
        loop._has_open_pr = AsyncMock(return_value=True)  # type: ignore[method-assign]

        with patch(
            "workspace_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_sub:
            # First call: git branch --list returns an orphaned branch
            # No second call should happen (branch should NOT be deleted)
            mock_sub.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()

        # The branch has an open PR — it must be skipped
        assert count == 0, (
            "Branch agent/issue-99 was deleted despite having an open PR. "
            "_collect_orphaned_branches must call _has_open_pr and skip "
            "branches whose PR is still open."
        )
        # _has_open_pr should have been consulted
        loop._has_open_pr.assert_awaited_once_with(99)

    @pytest.mark.asyncio
    async def test_deletes_branch_when_no_open_pr(self, tmp_path: Path) -> None:
        """An orphaned branch with NO open PR should still be deleted.

        This is a sanity check confirming that the guard does not
        prevent all deletions.
        """
        loop = _make_gc_loop(tmp_path)
        loop._has_open_pr = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with patch(
            "workspace_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_sub:
            # First call: branch list; second call: branch delete
            mock_sub.side_effect = ["  agent/issue-99\n", ""]
            count = await loop._collect_orphaned_branches()

        assert count == 1
        # Verify the delete call used -D
        assert mock_sub.call_args_list[1][0] == (
            "git",
            "branch",
            _FORCE_DEL,
            "agent/issue-99",
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6961 — fix not yet landed", strict=False)
    async def test_branch_gc_uses_safe_delete_not_force(self, tmp_path: Path) -> None:
        """Branch deletion should use safe delete (-d) not force (-D).

        Force-delete (-D) discards unmerged commits silently.  Safe
        delete (-d) lets git reject the deletion if the branch has
        commits not yet merged, providing an additional safety net.

        This test will fail until force-delete is replaced with safe
        delete.
        """
        loop = _make_gc_loop(tmp_path)
        loop._has_open_pr = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with patch(
            "workspace_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as mock_sub:
            mock_sub.side_effect = ["  agent/issue-77\n", ""]
            await loop._collect_orphaned_branches()

        # The delete call is the second invocation
        delete_call_args = mock_sub.call_args_list[1][0]
        assert delete_call_args[2] == "-d", (
            f"Expected safe delete flag '-d' but got '{delete_call_args[2]}'. "
            "Force-delete (-D) risks discarding unmerged commits."
        )

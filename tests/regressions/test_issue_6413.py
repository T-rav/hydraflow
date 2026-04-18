"""Regression test for issue #6413.

Bug: ``WorkspaceGCLoop._collect_orphaned_dirs`` calls
``repo_wt_base.iterdir()`` (line ~253) without catching ``OSError``.

If the worktree base directory exists but ``iterdir()`` fails (e.g.
network mount unavailable, permission denied), the ``OSError`` propagates
out of ``_do_work``, aborting the entire GC cycle mid-run.  Phase 1
(state-tracked workspaces) has already executed, but Phases 3-4
(orphaned branches, stale branch entries) are skipped.

Expected behaviour after fix:
  - ``OSError`` from ``iterdir()`` is caught and logged.
  - ``_collect_orphaned_dirs`` returns 0 so Phases 3-4 still run.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop


def _make_gc_loop(tmp_path: Path) -> tuple[WorkspaceGCLoop, MagicMock, MagicMock]:
    """Build a WorkspaceGCLoop with test-friendly mocks.

    Returns (loop, workspaces_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()

    prs = MagicMock()

    state = MagicMock()
    state.get_active_workspaces = MagicMock(return_value={})
    state.get_active_issue_numbers = MagicMock(return_value=set())
    state.get_hitl_cause = MagicMock(return_value=None)
    state.get_issue_attempts = MagicMock(return_value=0)
    state.remove_workspace = MagicMock()
    state.remove_branch = MagicMock()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _: False,
    )
    return loop, workspaces, state


class TestOSErrorOnIterdir:
    """OSError from iterdir() in _collect_orphaned_dirs must be caught, not propagated."""

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_returns_zero_on_oserror(
        self, tmp_path: Path
    ) -> None:
        """OSError from iterdir() should be caught and return 0.

        Current buggy code: no try/except around ``sorted(repo_wt_base.iterdir())``,
        so ``OSError`` propagates out of ``_collect_orphaned_dirs``.
        This test is RED until the OSError is caught.
        """
        loop, workspaces, state = _make_gc_loop(tmp_path)

        # Create the repo worktree base so the exists() check passes
        repo_wt_base = loop._config.workspace_base / loop._config.repo_slug
        repo_wt_base.mkdir(parents=True)

        # Patch iterdir on the specific Path instance to raise OSError
        with patch.object(
            type(repo_wt_base),
            "iterdir",
            side_effect=OSError("Network mount unavailable"),
        ):
            result = await loop._collect_orphaned_dirs({}, budget=10)

        # After fix: should return 0 instead of raising
        assert result == 0

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_returns_zero_on_permission_error(
        self, tmp_path: Path
    ) -> None:
        """PermissionError (subclass of OSError) from iterdir() should also be caught.

        Current buggy code: ``PermissionError`` propagates since it is an ``OSError``.
        This test is RED until the error is caught.
        """
        loop, workspaces, state = _make_gc_loop(tmp_path)

        repo_wt_base = loop._config.workspace_base / loop._config.repo_slug
        repo_wt_base.mkdir(parents=True)

        with patch.object(
            type(repo_wt_base), "iterdir", side_effect=PermissionError("Access denied")
        ):
            result = await loop._collect_orphaned_dirs({}, budget=10)

        assert result == 0

    @pytest.mark.asyncio
    async def test_do_work_phases_3_4_still_run_after_iterdir_oserror(
        self, tmp_path: Path
    ) -> None:
        """OSError in Phase 2 must not abort Phases 3 and 4.

        Current buggy code: the OSError from ``_collect_orphaned_dirs``
        propagates through ``_do_work``, skipping ``_collect_orphaned_branches``
        (Phase 3) and ``_prune_stale_branch_entries`` (Phase 4).

        This test is RED until the error is caught inside ``_collect_orphaned_dirs``.
        """
        loop, workspaces, state = _make_gc_loop(tmp_path)

        repo_wt_base = loop._config.workspace_base / loop._config.repo_slug
        repo_wt_base.mkdir(parents=True)

        # Patch _collect_orphaned_branches and _prune_stale_branch_entries to
        # track whether they're called
        loop._collect_orphaned_branches = AsyncMock(return_value=0)
        loop._prune_stale_branch_entries = AsyncMock(return_value=0)

        with patch.object(
            type(repo_wt_base),
            "iterdir",
            side_effect=OSError("Network mount unavailable"),
        ):
            # _do_work should NOT raise — it should catch the OSError in Phase 2
            # and continue to Phases 3 and 4
            await loop._do_work()

        # Phase 3 and Phase 4 must have been called
        loop._collect_orphaned_branches.assert_called_once()
        loop._prune_stale_branch_entries.assert_called_once()

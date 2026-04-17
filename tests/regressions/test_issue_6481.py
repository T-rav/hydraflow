"""Regression test for issue #6481.

Bug: ``workspace_gc_loop.WorkspaceGCLoop`` uses ``except Exception``
throughout ``_do_work`` and its sub-methods (``_collect_stale_workspaces``,
``_collect_orphaned_dirs``, ``_collect_orphaned_branches``,
``_prune_stale_branch_entries``).  Because ``AuthenticationError`` is a
subclass of ``RuntimeError`` (which is a subclass of ``Exception``), it
is silently swallowed and the GC loop continues running as if nothing
happened.  The orchestrator never learns that authentication has failed,
so the pipeline keeps looping uselessly while worktrees pile up.

Expected behaviour after fix:
  - ``AuthenticationError`` raised inside any GC phase propagates out
    of ``_do_work()`` (not caught by the broad ``except Exception``).
  - ``BaseBackgroundLoop._execute_cycle()`` then re-raises it (line 141
    of ``base_background_loop.py``), which the orchestrator handles.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from state import StateTracker
from subprocess_util import AuthenticationError
from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gc_loop(
    tmp_path: Path,
    *,
    active_workspaces: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    active_branches: dict[int, str] | None = None,
) -> WorkspaceGCLoop:
    """Build a WorkspaceGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)

    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)
    if active_issue_numbers:
        state.set_active_issue_numbers(active_issue_numbers)
    for num, branch in (active_branches or {}).items():
        state.set_branch(num, branch)

    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()
    prs = MagicMock()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _n: False,
    )
    return loop


# ---------------------------------------------------------------------------
# Phase 1: _collect_stale_workspaces — except Exception at line 73
# ---------------------------------------------------------------------------


class TestPhase1AuthErrorPropagates:
    """AuthenticationError in _is_safe_to_gc during Phase 1 must propagate."""

    @pytest.mark.asyncio
    async def test_auth_error_from_get_issue_state_propagates(
        self, tmp_path: Path
    ) -> None:
        """When _get_issue_state raises AuthenticationError while checking
        whether a tracked workspace is safe to GC, the error must NOT be
        caught by the ``except Exception`` at line 73.

        BUG (current): the broad handler catches it and increments the
        error counter instead of propagating.
        """
        loop = _make_gc_loop(
            tmp_path,
            active_workspaces={42: "/tmp/issue-42"},
        )
        # Stub _issue_has_pipeline_label so _is_safe_to_gc reaches _get_issue_state
        loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("Bad credentials"),
        )
        # Stub out phases 2-4 to isolate Phase 1
        loop._collect_orphaned_dirs = AsyncMock(return_value=0)  # type: ignore[method-assign]
        loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
        loop._prune_stale_branch_entries = AsyncMock(return_value=0)  # type: ignore[method-assign]

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._do_work()


# ---------------------------------------------------------------------------
# Phase 2: _collect_orphaned_dirs — except Exception at line 272
# ---------------------------------------------------------------------------


class TestPhase2AuthErrorPropagates:
    """AuthenticationError in _collect_orphaned_dirs must propagate."""

    @pytest.mark.asyncio
    async def test_auth_error_from_orphaned_dir_gc_check_propagates(
        self, tmp_path: Path
    ) -> None:
        """When _is_safe_to_gc raises AuthenticationError while scanning
        orphaned directories, the error must NOT be caught by the
        ``except Exception`` at line 272.

        BUG (current): the broad handler catches it and silently skips
        the orphaned directory.
        """
        loop = _make_gc_loop(tmp_path)
        # Phase 1: no tracked workspaces, so Phase 1 is a no-op.
        # Phase 2: create a fake orphaned issue dir on disk.
        workspace_base = loop._config.workspace_base / loop._config.repo_slug
        workspace_base.mkdir(parents=True, exist_ok=True)
        orphan_dir = workspace_base / "issue-99"
        orphan_dir.mkdir()

        loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("Bad credentials"),
        )
        # Stub out phases 3-4
        loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
        loop._prune_stale_branch_entries = AsyncMock(return_value=0)  # type: ignore[method-assign]

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._do_work()


# ---------------------------------------------------------------------------
# Phase 4: _prune_stale_branch_entries — except Exception at line 358
# ---------------------------------------------------------------------------


class TestPhase4AuthErrorPropagates:
    """AuthenticationError in _prune_stale_branch_entries must propagate."""

    @pytest.mark.asyncio
    async def test_auth_error_from_prune_branch_entries_propagates(
        self, tmp_path: Path
    ) -> None:
        """When _is_safe_to_gc raises AuthenticationError while pruning
        stale branch entries, the error must NOT be caught by the
        ``except Exception`` at line 358.

        BUG (current): the broad handler catches it and silently skips
        the entry.
        """
        loop = _make_gc_loop(
            tmp_path,
            active_branches={77: "agent/issue-77"},
        )
        loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("Bad credentials"),
        )
        # Stub out phases 1-3
        loop._collect_orphaned_dirs = AsyncMock(return_value=0)  # type: ignore[method-assign]
        loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._prune_stale_branch_entries()

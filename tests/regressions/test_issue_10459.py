"""Regression pin for issue #10459 — GC must not sweep an active auto-agent worktree.

``WorkspaceGCLoop._is_safe_to_gc`` guarded the *implementation* retry counter
(``get_issue_attempts``) but not the *auto_agent* convergence-ledger counter
(``get_auto_agent_attempts``). Both counters are bumped *before* each run and
cleared on success/close, so mid-session the issue is absent from every active
set. With only the implementation counter checked, an in-flight auto-agent
session's worktree was judged collectable and swept — losing its unpushed
commits (the #10403 race).

The fix consults *both* counters via ``_in_retry_window``, applied in every GC
phase (state sweep, orphan-dir sweep, orphan-branch sweep, stale-branch prune).

These tests prove:
- an in-window auto-agent attempt protects the worktree (state + branch phases),
- a genuinely-stale worktree (no attempts, closed issue) is still swept, and
- an exhausted auto-agent counter is *not* protected (no permanent leak).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Repo root on sys.path so ``tests.helpers`` imports (``src`` via PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from state import StateTracker  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402
from workspace_gc_loop import WorkspaceGCLoop  # noqa: E402


def _make_loop(
    tmp_path: Path,
    *,
    active_workspaces: dict[int, str] | None = None,
) -> tuple[WorkspaceGCLoop, StateTracker]:
    """Build a WorkspaceGCLoop backed by a real StateTracker."""
    deps = make_bg_loop_deps(tmp_path)
    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)

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
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return loop, state


class TestActiveAutoAgentWorktreePreserved:
    """#10459: an in-flight auto-agent session's worktree must survive GC."""

    @pytest.mark.asyncio
    async def test_in_window_auto_agent_attempt_skips_gc(self, tmp_path: Path) -> None:
        """Issue absent from active sets but holding an in-window auto-agent
        attempt (0<attempts<max) must NOT be swept, even though the issue is
        open with no PR (otherwise-collectable)."""
        loop, state = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        # In-flight auto-agent session: bumped before the run, not yet cleared.
        state.bump_auto_agent_attempts(42)
        assert 0 < state.get_auto_agent_attempts(42) < loop._config.auto_agent_max_attempts
        # Implementation counter untouched — only the auto-agent guard can save it.
        assert state.get_issue_attempts(42) == 0
        loop._get_issue_state = AsyncMock(return_value="open")  # type: ignore[method-assign]

        result = await loop._do_work()

        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_stale_worktree_still_swept(self, tmp_path: Path) -> None:
        """A genuinely-stale worktree (no attempts, closed issue) is still GC'd —
        the guard must not freeze all collection."""
        loop, state = _make_loop(tmp_path, active_workspaces={99: "/p/99"})
        # No auto-agent attempts recorded.
        assert state.get_auto_agent_attempts(99) == 0
        loop._get_issue_state = AsyncMock(return_value="closed")  # type: ignore[method-assign]

        result = await loop._do_work()

        loop._workspaces.destroy.assert_awaited_once_with(99)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_exhausted_auto_agent_attempts_not_protected(
        self, tmp_path: Path
    ) -> None:
        """Once the auto-agent counter is exhausted (==max) the worktree is no
        longer session-owned; the guard must release it so it can't leak."""
        loop, state = _make_loop(tmp_path, active_workspaces={7: "/p/7"})
        for _ in range(loop._config.auto_agent_max_attempts):
            state.bump_auto_agent_attempts(7)
        assert state.get_auto_agent_attempts(7) == loop._config.auto_agent_max_attempts
        loop._get_issue_state = AsyncMock(return_value="closed")  # type: ignore[method-assign]

        result = await loop._do_work()

        loop._workspaces.destroy.assert_awaited_once_with(7)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_orphan_branch_skipped_for_active_auto_agent(
        self, tmp_path: Path
    ) -> None:
        """Phase 3 (orphan branch deletion) must honour the same auto-agent
        retry-window guard, or it deletes the session's branch.

        Uses the real Auto-Agent branch name (``agent/auto-agent-<N>``, minted
        by ``AutoAgentPreflightLoop._resolve_worktree``) — a fabricated
        ``agent/issue-<N>`` name here would pass regardless of whether the
        guard is reachable, since that namespace was never in-flight for an
        auto-agent session in the first place (#11182).
        """
        loop, state = _make_loop(tmp_path)
        state.bump_auto_agent_attempts(88)  # in-flight auto-agent session
        # Restore the real method (the test factory stubs it out).
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[method-assign]

        # The branch must actually be attributed to #88 for the guard below
        # to be reachable at all — pin that separately from the outward
        # skip-count assertion, which a fail-closed "unparseable" skip would
        # satisfy just as well.
        assert WorkspaceGCLoop._parse_issue_from_branch("agent/auto-agent-88") == 88

        with patch(
            "workspace_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as run_sub:
            run_sub.return_value = "  agent/auto-agent-88\n"
            count = await loop._collect_orphaned_branches()

        assert count == 0
        assert run_sub.await_count == 1  # only the list call; no delete

    @pytest.mark.asyncio
    async def test_orphan_branch_deleted_for_stale_auto_agent_session(
        self, tmp_path: Path
    ) -> None:
        """A stale (no longer in-flight) ``agent/auto-agent-<N>`` branch must
        actually be reaped by phase 3.

        Before #11182, ``_parse_issue_from_branch`` never matched this
        namespace, so the branch was invisible to phase 3 regardless of the
        guard — an orphaned Auto-Agent branch leaked forever instead of being
        collected once its session ended.
        """
        loop, _state = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[method-assign]

        with patch(
            "workspace_gc_loop.run_subprocess", new_callable=AsyncMock
        ) as run_sub:
            run_sub.side_effect = ["  agent/auto-agent-89\n", ""]
            count = await loop._collect_orphaned_branches()

        assert count == 1
        assert run_sub.await_count == 2  # list + delete
        run_sub.assert_any_call(
            "git",
            "branch",
            "-D",
            "agent/auto-agent-89",
            cwd=loop._config.repo_root,
            gh_token=loop._credentials.gh_token,
        )


class TestInRetryWindowHelper:
    """Direct unit coverage of the extracted ``_in_retry_window`` predicate."""

    def test_auto_agent_in_window_true(self, tmp_path: Path) -> None:
        loop, state = _make_loop(tmp_path)
        state.bump_auto_agent_attempts(5)
        assert loop._in_retry_window(5) is True

    def test_impl_in_window_true(self, tmp_path: Path) -> None:
        loop, state = _make_loop(tmp_path)
        state.increment_issue_attempts(5)
        assert loop._in_retry_window(5) is True

    def test_no_attempts_false(self, tmp_path: Path) -> None:
        loop, _state = _make_loop(tmp_path)
        assert loop._in_retry_window(5) is False

    def test_exhausted_false(self, tmp_path: Path) -> None:
        loop, state = _make_loop(tmp_path)
        for _ in range(loop._config.auto_agent_max_attempts):
            state.bump_auto_agent_attempts(5)
        assert loop._in_retry_window(5) is False

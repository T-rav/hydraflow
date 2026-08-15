"""Tests for the WorkspaceGCLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from mockworld.fakes.fake_github import FakeGitHub
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import _MAX_GC_PER_CYCLE, WorkspaceGCLoop

# Force-delete flag for branch deletion assertions
_FORCE_DEL = chr(45) + chr(68)


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 600,
    active_workspaces: dict[int, str] | None = None,
    active_issue_numbers: list[int] | None = None,
    hitl_causes: dict[int, str] | None = None,
    pipeline_issues: set[int] | None = None,
    **config_overrides: object,
) -> tuple[WorkspaceGCLoop, StateTracker, asyncio.Event]:
    """Build a WorkspaceGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        workspace_gc_interval=interval,
        **config_overrides,
    )

    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)
    if active_issue_numbers:
        state.set_active_issue_numbers(active_issue_numbers)
    for num, cause in (hitl_causes or {}).items():
        state.set_hitl_cause(num, cause)

    in_pipeline = pipeline_issues or set()

    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()
    prs = MagicMock()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda n: n in in_pipeline,
    )
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
    # Phase 5 (enumerate-and-reap, #10698) shells out to `git worktree list`;
    # neutralize it in the shared helper so the existing issue-<N> phase tests
    # stay hermetic. Dedicated tests below exercise the real method.
    loop._collect_orphaned_worktrees = AsyncMock(return_value=0)  # type: ignore[method-assign]
    return loop, state, deps.stop_event


class TestWorkspaceGCLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "workspace_gc"

    def test_default_interval(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, enabled=False)
        await loop.run()
        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__publishes_status_on_success(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path)
        with patch.object(
            loop,
            "_do_work",
            new_callable=AsyncMock,
            return_value={"collected": 0, "skipped": 0, "errors": 0},
        ):
            await loop.run()
        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        assert events[0].data["worker"] == "workspace_gc"
        assert events[0].data["status"] == "ok"


class TestWorktreeGCCollectsClosedIssues:
    @pytest.mark.asyncio
    async def test_gc_closed_issue_worktree(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert 42 not in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_gc_returns_collected_count(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_state_removed_before_destroy(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        call_order: list[str] = []
        original_remove = state.remove_workspace

        def tracked_remove(num: int) -> None:
            call_order.append("remove_state")
            original_remove(num)

        state.remove_workspace = tracked_remove  # type: ignore[method-assign]

        async def tracked_destroy(num: int) -> None:
            call_order.append("destroy")

        loop._workspaces.destroy = tracked_destroy  # type: ignore[method-assign]
        await loop._do_work()
        assert call_order == ["remove_state", "destroy"]


class TestWorktreeGCSkipsActive:
    @pytest.mark.asyncio
    async def test_skips_active_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, active_issue_numbers=[42]
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_hitl_in_progress(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, hitl_causes={42: "ci_failure"}
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_open_issue_with_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_open_issue_without_pr(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_unknown_issue_state(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="unknown")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCSkipsRetryableIssues:
    """GC must not destroy worktrees for issues that still have retries remaining."""

    @pytest.mark.asyncio
    async def test_skips_issue_with_retries_remaining(self, tmp_path: Path) -> None:
        """Issue with 1/3 attempts used must not be GC'd."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.increment_issue_attempts(42)  # 1 attempt used
        loop._get_issue_state = AsyncMock(return_value="open")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_issue_at_penultimate_attempt(self, tmp_path: Path) -> None:
        """Issue with 2/3 attempts used still has one retry left."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.increment_issue_attempts(42)
        state.increment_issue_attempts(42)  # 2 attempts used, max is 3
        loop._get_issue_state = AsyncMock(return_value="open")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_gc_allowed_after_attempts_exhausted(self, tmp_path: Path) -> None:
        """Once all attempts are used, GC should proceed normally."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        for _ in range(loop._config.max_issue_attempts):
            state.increment_issue_attempts(42)  # exhaust all attempts
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_gc_allowed_when_zero_attempts(self, tmp_path: Path) -> None:
        """Issues with zero attempts (never started) are fine to GC."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        # No attempts recorded
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1


class TestWorktreeGCBudgetCap:
    @pytest.mark.asyncio
    async def test_budget_caps_phase1_at_max(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, _MAX_GC_PER_CYCLE + 5)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE
        assert loop._workspaces.destroy.await_count == _MAX_GC_PER_CYCLE

    @pytest.mark.asyncio
    async def test_budget_shared_across_phases(self, tmp_path: Path) -> None:
        wts = {i: f"/p/issue-{i}" for i in range(1, 6)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")
        calls: list[int] = []

        async def capture_budget(budget: int = _MAX_GC_PER_CYCLE) -> int:
            calls.append(budget)
            return 0

        loop._collect_orphaned_branches = capture_budget  # type: ignore[method-assign]
        await loop._do_work()
        assert calls == [_MAX_GC_PER_CYCLE - 5]


class TestWorktreeGCOrphanedDirs:
    @pytest.mark.asyncio
    async def test_collects_orphaned_filesystem_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        orphan = loop._config.workspace_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(99)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_non_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.workspace_base / loop._config.repo_slug
        (base / "random-dir").mkdir(parents=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_non_numeric_issue_dirs(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        base = loop._config.workspace_base / loop._config.repo_slug
        (base / "issue-abc").mkdir(parents=True)
        await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_when_base_missing(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result["collected"] == 0


class TestWorktreeGCOrphanedBranches:
    @pytest.mark.asyncio
    async def test_deletes_orphaned_branches(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-99\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-99")

    @pytest.mark.asyncio
    async def test_skips_branches_with_active_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={99: "/p/99"})
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1

    @pytest.mark.asyncio
    async def test_starred_branch_parsed_correctly(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["* agent/issue-77\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == ("git", "branch", _FORCE_DEL, "agent/issue-77")

    @pytest.mark.asyncio
    async def test_branch_list_failure_returns_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("git error")
            count = await loop._collect_orphaned_branches()
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_branch_when_labels_show_pipeline(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues=set())
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1

    @pytest.mark.asyncio
    async def test_skips_branch_with_retries_remaining(self, tmp_path: Path) -> None:
        """Branches for retryable issues must not be deleted."""
        loop, state, _e = _make_loop(tmp_path)
        state.increment_issue_attempts(99)  # 1 attempt, retries remain
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1  # only the branch list call, no delete

    @pytest.mark.asyncio
    async def test_branch_budget_cap(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        branches = "\n".join(f"  agent/issue-{i}" for i in range(1, 10))
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = branches
            count = await loop._collect_orphaned_branches(budget=3)
        assert count == 3
        assert m.await_count == 4


class TestWorktreeGCSubprocessArgs:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("port_state", "expected"),
        [
            ("COMPLETED", "closed"),
            ("NOT_PLANNED", "closed"),
            ("OPEN", "open"),
            ("UNKNOWN", "unknown"),
            ("", "unknown"),
        ],
    )
    async def test_get_issue_state_maps_port_vocabulary(
        self, tmp_path: Path, port_state: str, expected: str
    ) -> None:
        """#9543: issue state reads route via PRPort, not raw gh.

        The port speaks GraphQL-style (COMPLETED/NOT_PLANNED/OPEN/UNKNOWN);
        the mapping preserves the REST-style strings _is_safe_to_gc compares
        against, and anything unrecognized fails closed to "unknown".
        """
        loop, _s, _e = _make_loop(tmp_path)
        loop._prs.get_issue_state = AsyncMock(return_value=port_state)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            result = await loop._get_issue_state(42)
        m.assert_not_called()  # no raw subprocess
        assert result == expected
        loop._prs.get_issue_state.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_gc_collects_closed_issue_via_fake_github(
        self, tmp_path: Path
    ) -> None:
        """#9543 e2e slice: a FakeGitHub-closed issue's worktree is collected.

        Exercises the real _get_issue_state → PRPort.get_issue_state chain
        against FakeGitHub (the adapter the air-gapped sandbox serves), not a
        mocked _get_issue_state — proving the seeded-closed-issue collect path
        the s59 sandbox scenario asserts.
        """
        loop, state, _e = _make_loop(tmp_path, active_workspaces={7301: "/p/7301"})
        gh = FakeGitHub()
        gh.add_issue(7301, "done", "body", state="closed")
        loop._prs = gh
        result = await loop._do_work()
        assert result is not None
        assert result["collected"] == 1
        assert 7301 not in state.get_active_workspaces()
        loop._workspaces.destroy.assert_awaited_once_with(7301)

    @pytest.mark.asyncio
    async def test_gc_skips_issue_unknown_to_fake_github(self, tmp_path: Path) -> None:
        """An issue FakeGitHub never saw reports UNKNOWN → fail-closed skip."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={7301: "/p/7301"})
        loop._prs = FakeGitHub()  # issue 7301 not seeded → UNKNOWN
        result = await loop._do_work()
        assert result is not None
        assert result["collected"] == 0
        assert result["skipped"] == 1
        assert 7301 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_has_open_pr_queries_port_for_branch(self, tmp_path: Path) -> None:
        """#9575: _has_open_pr resolves the branch's PR via PRPort, not raw gh."""
        loop, _s, _e = _make_loop(tmp_path)
        from mockworld.fakes._factories import PRInfoFactory

        branch = loop._config.branch_for_issue(42)
        loop._prs.find_open_pr_for_branch = AsyncMock(
            return_value=PRInfoFactory.create(number=7, issue_number=42, branch=branch)
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            result = await loop._has_open_pr(42)
        m.assert_not_called()  # no raw subprocess
        assert result is True
        loop._prs.find_open_pr_for_branch.assert_awaited_once_with(
            branch, issue_number=42
        )

    @pytest.mark.asyncio
    async def test_has_open_pr_false_on_zero_sentinel(self, tmp_path: Path) -> None:
        """FakeGitHub signals 'no PR' with PRInfo(number=0) — must read as False."""
        loop, _s, _e = _make_loop(tmp_path)
        from mockworld.fakes._factories import PRInfoFactory

        loop._prs.find_open_pr_for_branch = AsyncMock(
            return_value=PRInfoFactory.create(number=0, issue_number=42, branch="b")
        )
        result = await loop._has_open_pr(42)
        assert result is False

    @pytest.mark.asyncio
    async def test_has_open_pr_returns_true_on_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._prs.find_open_pr_for_branch = AsyncMock(
            side_effect=RuntimeError("gh failed")
        )
        result = await loop._has_open_pr(42)
        assert result is True  # fail-closed: assume PR exists on error

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_reads_labels_via_port(
        self, tmp_path: Path
    ) -> None:
        """#9575: pipeline-label check reads labels via PRPort, not raw gh."""
        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._prs.get_issue_labels = AsyncMock(
            return_value=[loop._config.ready_label[0], "other-label"]
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            result = await loop._issue_has_pipeline_label(42)
        m.assert_not_called()  # no raw subprocess
        assert result is True
        loop._prs.get_issue_labels.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_fails_safe_on_api_error(
        self, tmp_path: Path
    ) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._prs.get_issue_labels = AsyncMock(side_effect=RuntimeError("gh failed"))
        result = await loop._issue_has_pipeline_label(42)
        assert result is True  # fail-closed: assume pipeline label present


class TestWorktreeGCErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API failure"))
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert 42 in state.get_active_workspaces()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_destroy_error_increments_error_count(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._workspaces.destroy = AsyncMock(side_effect=RuntimeError("destroy failed"))
        result = await loop._do_work()
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_has_open_pr_error_skips_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=RuntimeError("PR check failed"))
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1


class TestWorktreeGCStopEvent:
    @pytest.mark.asyncio
    async def test_stop_event_halts_gc(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(
            tmp_path, active_workspaces={1: "/p/1", 2: "/p/2", 3: "/p/3"}
        )
        stop.set()
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_stop_event_skips_later_phases(self, tmp_path: Path) -> None:
        loop, _s, stop = _make_loop(tmp_path, active_workspaces={42: "/p/42"})

        async def gc_and_stop(issue_number: int) -> str:
            stop.set()
            return "closed"

        loop._get_issue_state = AsyncMock(side_effect=gc_and_stop)
        result = await loop._do_work()
        assert result["collected"] == 1
        loop._collect_orphaned_branches.assert_not_awaited()


class TestWorktreeGCOrphanedDirsBudget:
    @pytest.mark.asyncio
    async def test_orphaned_dirs_respect_budget(self, tmp_path: Path) -> None:
        """Phase 2 stops collecting when budget is exhausted."""
        # Phase 1 collects 18, leaving budget of 2 for Phase 2
        wts = {i: f"/p/issue-{i}" for i in range(1, 19)}
        loop, _s, _e = _make_loop(tmp_path, active_workspaces=wts)
        loop._get_issue_state = AsyncMock(return_value="closed")

        # Create 5 orphaned dirs — only 2 should be collected (budget = 20 - 18)
        slug = loop._config.repo_slug
        for i in range(100, 105):
            (loop._config.workspace_base / slug / f"issue-{i}").mkdir(parents=True)

        result = await loop._do_work()
        assert result["collected"] == _MAX_GC_PER_CYCLE  # 18 + 2 = 20


class TestWorktreeGCOrphanedDirsErrors:
    @pytest.mark.asyncio
    async def test_orphaned_dir_destroy_failure_continues(self, tmp_path: Path) -> None:
        """A destroy failure for one orphaned dir does not stop processing others."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        (loop._config.workspace_base / slug / "issue-51").mkdir(parents=True)

        loop._get_issue_state = AsyncMock(return_value="closed")

        call_count = 0

        async def fail_then_succeed(issue_number: int) -> None:
            nonlocal call_count
            call_count += 1
            if issue_number == 50:
                raise RuntimeError("destroy failed")

        loop._workspaces.destroy = fail_then_succeed  # type: ignore[method-assign]

        result = await loop._do_work()
        # issue-50 fails, issue-51 succeeds
        assert call_count == 2
        assert result["collected"] >= 1


class TestWorktreeGCStopEventPhase2:
    @pytest.mark.asyncio
    async def test_stop_event_halts_orphaned_dir_iteration(
        self, tmp_path: Path
    ) -> None:
        """Stop event set during Phase 2 stops collecting orphaned dirs."""
        loop, _s, stop = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        for i in range(100, 105):
            (loop._config.workspace_base / slug / f"issue-{i}").mkdir(parents=True)

        call_count = 0

        async def gc_and_stop_on_second(issue_number: int) -> str:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                stop.set()
            return "closed"

        loop._get_issue_state = AsyncMock(side_effect=gc_and_stop_on_second)

        result = await loop._do_work()
        # Should stop after 2 orphaned dirs due to stop event
        assert result["collected"] <= 3


class TestWorktreeGCBranchActiveIssues:
    @pytest.mark.asyncio
    async def test_skips_branches_with_active_issue_number(
        self, tmp_path: Path
    ) -> None:
        """Branches for active issues (no worktree entry) are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, active_issue_numbers=[99])
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1


class TestIsSafeToGCDirect:
    """Direct unit tests for _is_safe_to_gc."""

    @pytest.mark.asyncio
    async def test_safe_for_closed_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="closed")
        assert await loop._is_safe_to_gc(42) is True

    @pytest.mark.asyncio
    async def test_unsafe_for_active_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, active_issue_numbers=[42])
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_for_hitl_issue(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, hitl_causes={42: "ci_failure"})
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_for_open_issue_with_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=True)
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_safe_for_open_issue_without_pr(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(return_value=False)
        assert await loop._is_safe_to_gc(42) is True

    @pytest.mark.asyncio
    async def test_unsafe_for_open_issue_with_pipeline_label(
        self, tmp_path: Path
    ) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._has_open_pr = AsyncMock(return_value=False)
        assert await loop._is_safe_to_gc(42) is False
        loop._has_open_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unsafe_on_api_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(side_effect=RuntimeError("API error"))
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_on_unknown_state(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="weird_state")
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_on_pr_check_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=RuntimeError("PR check error"))
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_unsafe_when_issue_in_pipeline(self, tmp_path: Path) -> None:
        """Issues queued/in-flight/active in IssueStore must not be GC'd."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={42})
        assert await loop._is_safe_to_gc(42) is False

    @pytest.mark.asyncio
    async def test_safe_when_issue_not_in_pipeline(self, tmp_path: Path) -> None:
        """Issues not in the pipeline can be GC'd if other checks pass."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        loop._get_issue_state = AsyncMock(return_value="closed")
        assert await loop._is_safe_to_gc(42) is True


class TestWorktreeGCPipelineProtection:
    @pytest.mark.asyncio
    async def test_skips_worktree_for_queued_issue(self, tmp_path: Path) -> None:
        """Worktrees for issues still in the pipeline queue are not collected."""
        loop, state, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, pipeline_issues={42}
        )
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_collects_worktree_not_in_pipeline(self, tmp_path: Path) -> None:
        """Worktrees for issues no longer in the pipeline are collected normally."""
        loop, _s, _e = _make_loop(
            tmp_path, active_workspaces={42: "/p/42"}, pipeline_issues=set()
        )
        loop._get_issue_state = AsyncMock(return_value="closed")
        result = await loop._do_work()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_skips_when_store_pipeline_stale_but_labels_show_queued(
        self, tmp_path: Path
    ) -> None:
        """GitHub labels protect queued issues even if IssueStore callback misses them."""
        loop, state, _e = _make_loop(
            tmp_path,
            active_workspaces={42: "/p/42"},
            pipeline_issues=set(),
        )
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._issue_has_pipeline_label = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._has_open_pr = AsyncMock(return_value=False)

        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["skipped"] == 1
        assert 42 in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_skips_orphaned_dir_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Orphaned filesystem dirs for pipeline issues are not collected."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        orphan = loop._config.workspace_base / loop._config.repo_slug / "issue-99"
        orphan.mkdir(parents=True)
        result = await loop._do_work()
        loop._workspaces.destroy.assert_not_awaited()
        assert result["collected"] == 0

    @pytest.mark.asyncio
    async def test_skips_branch_for_pipeline_issue(self, tmp_path: Path) -> None:
        """Branches for issues in the pipeline are not deleted."""
        loop, _s, _e = _make_loop(tmp_path, pipeline_issues={99})
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1


class TestGCRemovesBranchStateOnWorktreeCollection:
    """Phase 1: GC'ing a worktree also removes its active_branches entry."""

    @pytest.mark.asyncio
    async def test_phase1_removes_branch_entry(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_phase1_noop_when_no_branch_entry(self, tmp_path: Path) -> None:
        """No error when GC'ing a worktree that has no branch entry."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(return_value="closed")
        await loop._do_work()
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_phase1_removes_branch_before_destroy(self, tmp_path: Path) -> None:
        """remove_branch must be called before destroy (crash-safe ordering)."""
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")

        call_order: list[str] = []
        original_remove_branch = state.remove_branch

        def tracked_remove_branch(num: int) -> None:
            call_order.append("remove_branch")
            original_remove_branch(num)

        async def tracked_destroy(num: int) -> None:
            call_order.append("destroy")

        state.remove_branch = tracked_remove_branch  # type: ignore[method-assign]
        loop._workspaces.destroy = tracked_destroy  # type: ignore[method-assign]
        await loop._do_work()
        assert "remove_branch" in call_order
        assert call_order.index("remove_branch") < call_order.index("destroy")


class TestGCRemovesBranchStateOnOrphanedBranchDeletion:
    """Phase 3: deleting an orphaned branch also removes its state entry."""

    @pytest.mark.asyncio
    async def test_phase3_removes_branch_entry(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(99, "agent/issue-99")
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-99\n", ""]
            await loop._collect_orphaned_branches()
        assert state.get_branch(99) is None

    @pytest.mark.asyncio
    async def test_phase3_preserves_unrelated_branch_entry_for_same_issue(
        self, tmp_path: Path
    ) -> None:
        """Deleting a stale branch in one namespace must NOT evict a tracked
        ``active_branches`` entry that points at a *different*, still-live
        branch for the same issue number (#11182).

        Two namespaces (e.g. ``agent/auto-agent-<N>`` and ``agent/issue-<N>``)
        can share an issue number. If the live ``agent/issue-99`` implement
        branch is tracked while a stale ``agent/auto-agent-99`` branch is
        swept, the tracked entry must survive — it names a branch that was
        never touched.
        """
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(99, "agent/issue-99")  # live impl branch, tracked
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            # Only the stale auto-agent branch is listed/deleted; agent/issue-99
            # is untouched (it has a live worktree so it isn't even listed here).
            m.side_effect = ["  agent/auto-agent-99\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert state.get_branch(99) == "agent/issue-99"


class TestGCPrunesStaleActiveBranches:
    """Phase 4: prune active_branches entries with no worktree and safe to GC."""

    @pytest.mark.asyncio
    async def test_prunes_stale_branch_without_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        # No worktree set for issue 42
        loop._is_safe_to_gc = AsyncMock(return_value=True)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 1
        assert state.get_branch(42) is None

    @pytest.mark.asyncio
    async def test_skips_branch_with_active_worktree(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(return_value=True)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0
        assert state.get_branch(42) == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_skips_branch_not_safe_to_gc(self, tmp_path: Path) -> None:
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(return_value=False)
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0
        assert state.get_branch(42) == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_phase4_runs_in_do_work(self, tmp_path: Path) -> None:
        """Phase 4 runs as part of the full _do_work cycle."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._get_issue_state = AsyncMock(return_value="closed")
        # _collect_orphaned_branches is already mocked in _make_loop
        result = await loop._do_work()
        assert state.get_branch(42) is None
        assert result["collected"] >= 1

    @pytest.mark.asyncio
    async def test_exception_during_pruning_skips_entry_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception during _is_safe_to_gc is caught; remaining entries are still pruned."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(10, "agent/issue-10")
        state.set_branch(20, "agent/issue-20")

        async def fail_first(issue_number: int) -> bool:
            if issue_number == 10:
                raise RuntimeError("API failure")
            return True

        loop._is_safe_to_gc = AsyncMock(side_effect=fail_first)
        pruned = await loop._prune_stale_branch_entries()
        # issue 10 raised — skipped; issue 20 succeeded — pruned
        assert pruned == 1
        assert state.get_branch(10) == "agent/issue-10"
        assert state.get_branch(20) is None


class TestCollectOrphanedBranchesPerItemIsolation:
    """Per-item try/except in _collect_orphaned_branches prevents one failure from aborting the pass."""

    @pytest.mark.asyncio
    async def test_pipeline_check_error_skips_branch_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception in _issue_has_pipeline_label for one branch doesn't abort the loop."""
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]

        call_count = 0

        async def fail_for_first(issue_number: int) -> bool:
            nonlocal call_count
            call_count += 1
            if issue_number == 10:
                raise RuntimeError("API failure")
            return False

        loop._issue_has_pipeline_label = AsyncMock(side_effect=fail_for_first)  # type: ignore[method-assign]

        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-10\n  agent/issue-20\n", ""]
            count = await loop._collect_orphaned_branches()

        # issue-10 raised — skipped; issue-20 succeeded — deleted
        assert count == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_is_in_pipeline_error_skips_branch_and_continues(
        self, tmp_path: Path
    ) -> None:
        """An exception in is_in_pipeline callback doesn't abort the loop."""
        call_log: list[int] = []

        def exploding_pipeline(n: int) -> bool:
            call_log.append(n)
            if n == 10:
                raise RuntimeError("callback boom")
            return False

        deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
        state = StateTracker(deps.config.state_file)
        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=MagicMock(),
            prs=MagicMock(),
            state=state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=exploding_pipeline,
        )
        loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  agent/issue-10\n  agent/issue-20\n", ""]
            count = await loop._collect_orphaned_branches()

        # issue-10 raised in pipeline check — skipped; issue-20 succeeded
        assert count == 1
        assert 10 in call_log
        assert 20 in call_log


class TestGCReraisesFatalExceptions:
    """Fatal exceptions (AuthenticationError, CreditExhaustedError, likely bugs)
    must propagate through GC except blocks instead of being swallowed as warnings.
    """

    # -- Phase 1: _do_work except block (line 73) --

    @pytest.mark.asyncio
    async def test_phase1_reraises_authentication_error(self, tmp_path: Path) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _do_work."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_phase1_reraises_attribute_error(self, tmp_path: Path) -> None:
        """AttributeError (likely bug) from _is_safe_to_gc propagates out of _do_work."""
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._do_work()

    # -- _is_safe_to_gc: _get_issue_state except block (line 141) --

    @pytest.mark.asyncio
    async def test_is_safe_to_gc_reraises_auth_error_from_get_issue_state(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _get_issue_state propagates out of _is_safe_to_gc."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._is_safe_to_gc(42)

    # -- _is_safe_to_gc: _has_open_pr except block (line 163) --

    @pytest.mark.asyncio
    async def test_is_safe_to_gc_reraises_auth_error_from_has_open_pr(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _has_open_pr propagates out of _is_safe_to_gc."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._get_issue_state = AsyncMock(return_value="open")
        loop._has_open_pr = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._is_safe_to_gc(42)

    # -- _issue_has_pipeline_label except block --

    @pytest.mark.asyncio
    async def test_issue_has_pipeline_label_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from PRPort.get_issue_labels propagates out."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._issue_has_pipeline_label = (
            WorkspaceGCLoop._issue_has_pipeline_label.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._prs.get_issue_labels = AsyncMock(
            side_effect=AuthenticationError("bad token")
        )
        with pytest.raises(AuthenticationError):
            await loop._issue_has_pipeline_label(42)

    # -- _collect_orphaned_dirs except block (line 272) --

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _collect_orphaned_dirs."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._get_issue_state = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._collect_orphaned_dirs({}, 10)

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) from _is_safe_to_gc propagates out of _collect_orphaned_dirs."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._get_issue_state = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._collect_orphaned_dirs({}, 10)

    # -- _collect_orphaned_branches per-item except block (line 333) --

    @pytest.mark.asyncio
    async def test_collect_orphaned_branches_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _issue_has_pipeline_label propagates out of _collect_orphaned_branches."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("bad token")
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            with pytest.raises(AuthenticationError):
                await loop._collect_orphaned_branches()

    @pytest.mark.asyncio
    async def test_collect_orphaned_branches_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) in branch processing propagates."""
        loop, _s, _e = _make_loop(tmp_path)
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined]
        loop._issue_has_pipeline_label = AsyncMock(  # type: ignore[method-assign]
            side_effect=AttributeError("no such attr")
        )
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "  agent/issue-99\n"
            with pytest.raises(AttributeError):
                await loop._collect_orphaned_branches()

    # -- _prune_stale_branch_entries except block (line 358) --

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_reraises_auth_error(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from _is_safe_to_gc propagates out of _prune_stale_branch_entries."""
        from subprocess_util import AuthenticationError  # noqa: PLC0415

        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=AuthenticationError("bad token"))
        with pytest.raises(AuthenticationError):
            await loop._prune_stale_branch_entries()

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_reraises_attribute_error(
        self, tmp_path: Path
    ) -> None:
        """AttributeError (likely bug) propagates out of _prune_stale_branch_entries."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=AttributeError("no such attr"))
        with pytest.raises(AttributeError):
            await loop._prune_stale_branch_entries()

    # -- Transient errors are still caught (regression safety) --

    @pytest.mark.asyncio
    async def test_phase1_still_catches_runtime_error(self, tmp_path: Path) -> None:
        """RuntimeError (transient) is still caught, not re-raised."""
        loop, _s, _e = _make_loop(tmp_path, active_workspaces={42: "/p/42"})
        loop._get_issue_state = AsyncMock(
            side_effect=RuntimeError("transient network error")
        )
        # RuntimeError is caught in _is_safe_to_gc (returns False → skipped)
        # and does not propagate to _do_work.
        result = await loop._do_work()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_collect_orphaned_dirs_still_catches_os_error(
        self, tmp_path: Path
    ) -> None:
        """OSError (transient filesystem) is still caught in _collect_orphaned_dirs."""
        loop, _s, _e = _make_loop(tmp_path)
        slug = loop._config.repo_slug
        (loop._config.workspace_base / slug / "issue-50").mkdir(parents=True)
        loop._is_safe_to_gc = AsyncMock(side_effect=OSError("disk error"))
        collected = await loop._collect_orphaned_dirs({}, 10)
        assert collected == 0  # error was caught, not propagated

    @pytest.mark.asyncio
    async def test_prune_stale_branch_entries_still_catches_runtime_error(
        self, tmp_path: Path
    ) -> None:
        """RuntimeError (transient) is still caught in _prune_stale_branch_entries."""
        loop, state, _e = _make_loop(tmp_path)
        state.set_branch(42, "agent/issue-42")
        loop._is_safe_to_gc = AsyncMock(side_effect=RuntimeError("API failure"))
        pruned = await loop._prune_stale_branch_entries()
        assert pruned == 0  # error was caught, not propagated


class TestWorkspaceGCReadsViaPort:
    """#9575: the open-issue GC branch reads GitHub through PRPort.

    ``_issue_has_pipeline_label`` and ``_has_open_pr`` must resolve issue
    labels / open-PR status through the injected ``PRPort`` rather than a raw
    ``gh`` subprocess. Routing through the Port means the air-gapped sandbox
    ``FakeGitHub`` can serve these reads, so the open-issue GC path becomes
    exercisable (it previously fail-closed under the sandbox network).
    """

    def _loop_with_fake(
        self, tmp_path: Path, fake: FakeGitHub
    ) -> tuple[WorkspaceGCLoop, StateTracker]:
        deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
        state = StateTracker(deps.config.state_file)
        workspaces = MagicMock()
        workspaces.destroy = AsyncMock()
        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=workspaces,
            prs=fake,
            state=state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _n: False,
        )
        return loop, state

    @pytest.mark.asyncio
    async def test_pipeline_label_true_via_port_no_subprocess(
        self, tmp_path: Path
    ) -> None:
        fake = FakeGitHub()
        loop, _state = self._loop_with_fake(tmp_path, fake)
        ready = loop._config.ready_label[0]
        fake.add_issue(42, "t", "b", labels=[ready, "some-other"])
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = ""  # if it shells out, it would see "no labels"
            result = await loop._issue_has_pipeline_label(42)
        m.assert_not_called()
        assert result is True

    @pytest.mark.asyncio
    async def test_pipeline_label_false_via_port_no_subprocess(
        self, tmp_path: Path
    ) -> None:
        fake = FakeGitHub()
        loop, _state = self._loop_with_fake(tmp_path, fake)
        fake.add_issue(42, "t", "b", labels=["not-a-pipeline-label"])
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "hydraflow-ready\n"  # if it shells out, it'd be True
            result = await loop._issue_has_pipeline_label(42)
        m.assert_not_called()
        assert result is False

    @pytest.mark.asyncio
    async def test_has_open_pr_true_via_port_no_subprocess(
        self, tmp_path: Path
    ) -> None:
        fake = FakeGitHub()
        loop, _state = self._loop_with_fake(tmp_path, fake)
        branch = loop._config.branch_for_issue(42)
        fake.add_issue(42, "t", "b")
        fake.add_pr(number=7, issue_number=42, branch=branch)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "0\n"  # if it shells out, it would see "no PR"
            result = await loop._has_open_pr(42)
        m.assert_not_called()
        assert result is True

    @pytest.mark.asyncio
    async def test_has_open_pr_false_via_port_no_subprocess(
        self, tmp_path: Path
    ) -> None:
        fake = FakeGitHub()
        loop, _state = self._loop_with_fake(tmp_path, fake)
        fake.add_issue(42, "t", "b")  # no PR for the branch
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.return_value = "1\n"  # if it shells out, it would report a PR
            result = await loop._has_open_pr(42)
        m.assert_not_called()
        assert result is False

    @pytest.mark.asyncio
    async def test_open_issue_gc_end_to_end_under_fake(self, tmp_path: Path) -> None:
        """Open issue with no pipeline labels and no PR is GC'd via the fake port."""
        fake = FakeGitHub()
        loop, state = self._loop_with_fake(tmp_path, fake)
        state.set_workspace(42, "/p/42")
        fake.add_issue(42, "t", "b")  # open, no labels, no PR
        # _get_issue_state still shells out (out of #9575 scope); stub to open.
        loop._get_issue_state = AsyncMock(return_value="open")
        # Phases 3 and 5 shell out for `git branch` / `git worktree list`; stub
        # both so the assertion below can prove the open-issue *label/PR* reads
        # never touched a subprocess.
        loop._collect_orphaned_branches = AsyncMock(return_value=0)
        loop._collect_orphaned_worktrees = AsyncMock(return_value=0)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            result = await loop._do_work()
        m.assert_not_called()
        loop._workspaces.destroy.assert_awaited_once_with(42)
        assert result["collected"] >= 1


# ===========================================================================
# #10698: all-root worktree coverage — branch parser + enumerate-and-reap
# ===========================================================================


class TestParseIssueFromBranch:
    """The branch→issue parser must cover every real namespace + fail closed."""

    @pytest.mark.parametrize(
        ("branch", "expected"),
        [
            ("issue-42", 42),
            ("agent/issue-42", 42),
            ("refs/heads/agent/issue-42", 42),
            ("agent/auto-agent-88", 88),  # #11182: Auto-Agent session branches
            ("fix/broaden-gc-coverage-10698", 10698),
            ("feat/operator-console-shell-10556", 10556),
            ("refactor/extract-thing-777", 777),
            ("chore/wiki-maintenance-10461", 10461),
            ("test/add-scenario-9001", 9001),
            ("docs/adr-rewrite-1234", 1234),
            ("fix/multi-9-part-88-500", 500),  # trailing suffix wins
        ],
    )
    def test_parses_all_namespaces(self, branch: str, expected: int) -> None:
        assert WorkspaceGCLoop._parse_issue_from_branch(branch) == expected

    @pytest.mark.parametrize(
        "branch",
        [
            None,
            "",
            "main",
            "staging",
            "rc/2026-07-26-1200",
            "fix/no-trailing-number",
            "feat/slug-without-issue",
            "issue-abc",
            "random/branch-name",
            # #11182: auto-agent lookalikes — suffix must be digits only.
            "agent/auto-agent-88-x",
            "agent/auto-agent-x",
            "auto-agent-88",  # bare — prefix must carry the agent/ scope
        ],
    )
    def test_unparseable_returns_none(self, branch: str | None) -> None:
        assert WorkspaceGCLoop._parse_issue_from_branch(branch) is None


class TestBroadenedBranchReaper:
    """Phase 3 now reaps fix/feat/… branches, not just agent/issue-*."""

    def _real_branch_reaper(self, loop: WorkspaceGCLoop) -> None:
        loop._collect_orphaned_branches = (
            WorkspaceGCLoop._collect_orphaned_branches.__get__(loop)
        )  # type: ignore[attr-defined,method-assign]

    @pytest.mark.asyncio
    async def test_deletes_fix_namespace_branch(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        self._real_branch_reaper(loop)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  fix/broaden-gc-10698\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 1
        assert m.call_args_list[1][0] == (
            "git",
            "branch",
            _FORCE_DEL,
            "fix/broaden-gc-10698",
        )

    @pytest.mark.asyncio
    async def test_lists_all_branches_no_pattern(self, tmp_path: Path) -> None:
        """The list call is no longer scoped to agent/issue-* (#10698)."""
        loop, _s, _e = _make_loop(tmp_path)
        self._real_branch_reaper(loop)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["", ""]
            await loop._collect_orphaned_branches()
        assert m.call_args_list[0][0] == ("git", "branch", "--list")

    @pytest.mark.asyncio
    async def test_skips_protected_branches(self, tmp_path: Path) -> None:
        """main/staging/rc branches parse to no issue → never deleted."""
        loop, _s, _e = _make_loop(tmp_path)
        self._real_branch_reaper(loop)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  main\n  staging\n* rc/2026-07-26-1200\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1  # only the list call; nothing deleted

    @pytest.mark.asyncio
    async def test_feat_branch_skipped_when_in_retry_window(
        self, tmp_path: Path
    ) -> None:
        """Broadened namespaces keep the same skip guards."""
        loop, state, _e = _make_loop(tmp_path)
        state.increment_issue_attempts(555)  # in retry window
        self._real_branch_reaper(loop)
        with patch("workspace_gc_loop.run_subprocess", new_callable=AsyncMock) as m:
            m.side_effect = ["  feat/new-thing-555\n", ""]
            count = await loop._collect_orphaned_branches()
        assert count == 0
        assert m.await_count == 1  # list only, no delete


class TestListGitWorktrees:
    """Porcelain parsing must yield (path, branch) and skip bare/locked."""

    @pytest.mark.asyncio
    async def test_parses_branches_and_detached(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        porcelain = (
            "worktree /repo/main\n"
            "HEAD abc\n"
            "branch refs/heads/staging\n"
            "\n"
            "worktree /wt/fix\n"
            "HEAD def\n"
            "branch refs/heads/fix/broaden-10698\n"
            "\n"
            "worktree /wt/detached\n"
            "HEAD 999\n"
            "detached\n"
        )
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value=porcelain,
        ):
            entries = await loop._list_git_worktrees()
        branches = {str(e.path): e.branch for e in entries}
        assert branches["/wt/fix"] == "fix/broaden-10698"
        assert branches["/repo/main"] == "staging"
        assert branches["/wt/detached"] is None

    @pytest.mark.asyncio
    async def test_skips_bare_and_locked(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        porcelain = (
            "worktree /repo/bare\n"
            "HEAD abc\n"
            "bare\n"
            "\n"
            "worktree /wt/locked\n"
            "HEAD def\n"
            "branch refs/heads/fix/thing-1\n"
            "locked initializing\n"
            "\n"
            "worktree /wt/live\n"
            "HEAD 111\n"
            "branch refs/heads/fix/thing-2\n"
        )
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value=porcelain,
        ):
            entries = await loop._list_git_worktrees()
        paths = {str(e.path) for e in entries}
        assert paths == {"/wt/live"}


class TestWorktreeGuards:
    """Direct tests of the fail-closed worktree guards."""

    @pytest.mark.asyncio
    async def test_dirty_true_when_status_nonempty(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value=" M file.py\n",
        ):
            assert await loop._worktree_is_dirty(Path("/wt")) is True

    @pytest.mark.asyncio
    async def test_dirty_false_when_clean(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value="",
        ):
            assert await loop._worktree_is_dirty(Path("/wt")) is False

    @pytest.mark.asyncio
    async def test_dirty_fails_closed_on_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            side_effect=RuntimeError("git boom"),
        ):
            assert await loop._worktree_is_dirty(Path("/wt")) is True

    @pytest.mark.asyncio
    async def test_unmerged_true_when_count_positive(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value="3\n",
        ):
            assert await loop._worktree_has_unmerged_commits(Path("/wt")) is True

    @pytest.mark.asyncio
    async def test_unmerged_false_when_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            return_value="0\n",
        ):
            assert await loop._worktree_has_unmerged_commits(Path("/wt")) is False

    @pytest.mark.asyncio
    async def test_unmerged_fails_closed_on_error(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            side_effect=RuntimeError("bad ref"),
        ):
            assert await loop._worktree_has_unmerged_commits(Path("/wt")) is True

    def test_too_new_false_when_min_age_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_min_age_seconds=0)
        assert loop._worktree_too_new(tmp_path) is False

    def test_too_new_true_for_fresh_dir(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_min_age_seconds=3600)
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        assert loop._worktree_too_new(fresh) is True

    def test_too_new_fails_closed_on_missing_path(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_min_age_seconds=3600)
        assert loop._worktree_too_new(tmp_path / "nope") is True


class TestCollectOrphanedWorktrees:
    """Phase 5 (#10698): enumerate-and-reap across all roots, fail-closed."""

    def _real_phase5(self, loop: WorkspaceGCLoop) -> None:
        loop._collect_orphaned_worktrees = (
            WorkspaceGCLoop._collect_orphaned_worktrees.__get__(loop)
        )  # type: ignore[attr-defined,method-assign]

    @staticmethod
    def _dispatch(
        *,
        worktrees: str,
        status: str = "",
        revlist: str = "0",
        removed: list[str] | None = None,
        deleted_branches: list[str] | None = None,
    ) -> AsyncMock:
        """A command-aware run_subprocess fake recording reap operations."""

        async def _fn(*cmd: str, **_kw: object) -> str:
            if cmd[:3] == ("git", "worktree", "list"):
                return worktrees
            if cmd[:3] == ("git", "status", "--porcelain"):
                return status
            if cmd[:2] == ("git", "rev-list"):
                return revlist
            if cmd[:3] == ("git", "worktree", "remove"):
                if removed is not None:
                    removed.append(cmd[-1])
                return ""
            if cmd[:3] == ("git", "branch", "-D"):
                if deleted_branches is not None:
                    deleted_branches.append(cmd[-1])
                return ""
            return ""

        return AsyncMock(side_effect=_fn)

    @pytest.mark.asyncio
    async def test_reaps_closed_issue_fix_worktree_on_nonstandard_root(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "sub-agent-worktrees"
        wt = root / "agent-abc"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/fix/broaden-gc-10698\n"
        removed: list[str] = []
        deleted: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(
                worktrees=porcelain, removed=removed, deleted_branches=deleted
            ),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 1
        assert removed == [str(wt.resolve())]
        assert deleted == ["fix/broaden-gc-10698"]

    @pytest.mark.asyncio
    async def test_keeps_dirty_worktree(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        wt = root / "dirty"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/fix/thing-10698\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, status=" M code.py\n", removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_keeps_open_issue_with_unmerged_commits(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        wt = root / "inflight"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="open")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/fix/thing-10698\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, revlist="4", removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_keeps_worktree_not_safe_to_gc(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        wt = root / "active"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=False)  # type: ignore[method-assign]
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/fix/thing-10698\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_keeps_inflight_auto_agent_worktree(self, tmp_path: Path) -> None:
        """An in-flight ``agent/auto-agent-<N>`` worktree (retry window active)
        is preserved by phase 5 — the branch must attribute to its issue so
        ``_is_safe_to_gc`` is consulted, not the unattributed "reap if empty"
        path (#11182).

        Before the fix ``_parse_issue_from_branch`` returned ``None`` for this
        namespace, so a clean, 0-unique-commit in-flight worktree was reaped
        without the retry-window guard — a #10459-style data-loss-adjacent gap.
        """
        root = tmp_path / "roots"
        wt = root / "auto-agent"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=False)  # type: ignore[method-assign]
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/agent/auto-agent-88\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []
        # The attribution contract itself: the auto-agent branch must route
        # through the attributed guard, not the unattributed reap-if-empty
        # path — pin that the guard was consulted for the parsed issue.
        loop._is_safe_to_gc.assert_awaited_once_with(88)

    @pytest.mark.asyncio
    async def test_reap_preserves_unrelated_branch_entry_for_same_issue(
        self, tmp_path: Path
    ) -> None:
        """Reaping a worktree in one namespace must NOT evict a tracked
        ``active_branches`` entry naming a *different*, still-live branch
        for the same issue (#11182) — the same cross-namespace aliasing
        guard phase 3 carries.
        """
        root = tmp_path / "roots"
        wt = root / "auto-agent"
        wt.mkdir(parents=True)
        loop, state, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        state.set_branch(99, "agent/issue-99")  # live impl branch, tracked
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/agent/auto-agent-99\n"
        removed: list[str] = []
        deleted: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(
                worktrees=porcelain, removed=removed, deleted_branches=deleted
            ),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 1
        assert deleted == ["agent/auto-agent-99"]
        assert state.get_branch(99) == "agent/issue-99"

    @pytest.mark.asyncio
    async def test_reap_evicts_branch_entry_naming_the_deleted_branch(
        self, tmp_path: Path
    ) -> None:
        """When the tracked entry names the branch just reaped, it IS evicted
        — the aliasing guard must not turn into permanent retention."""
        root = tmp_path / "roots"
        wt = root / "impl"
        wt.mkdir(parents=True)
        loop, state, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        state.set_branch(99, "agent/issue-99")  # tracked entry == reaped branch
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/agent/issue-99\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 1
        assert state.get_branch(99) is None

    @pytest.mark.asyncio
    async def test_reaps_unparseable_only_when_provably_empty(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "roots"
        wt = root / "spike"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        # No issue resolvable from a detached worktree; clean + 0 unique commits.
        porcelain = f"worktree {wt}\nHEAD abc\ndetached\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, revlist="0", removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 1
        assert removed == [str(wt.resolve())]

    @pytest.mark.asyncio
    async def test_keeps_unparseable_with_unique_commits(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        wt = root / "spike"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        self._real_phase5(loop)
        porcelain = f"worktree {wt}\nHEAD abc\ndetached\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, revlist="2", removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_skips_worktree_outside_allowed_roots(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(allowed)])
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {outside}\nHEAD abc\nbranch refs/heads/fix/x-10698\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_skips_too_new_worktree(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        wt = root / "fresh"
        wt.mkdir(parents=True)
        loop, _s, _e = _make_loop(
            tmp_path,
            worktree_gc_roots=[str(root)],
            worktree_gc_min_age_seconds=3600,
        )
        self._real_phase5(loop)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]
        loop._get_issue_state = AsyncMock(return_value="closed")
        porcelain = f"worktree {wt}\nHEAD abc\nbranch refs/heads/fix/x-10698\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_never_reaps_primary_worktree(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        self._real_phase5(loop)
        repo_root = loop._config.repo_root.expanduser().resolve()
        porcelain = f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/staging\n"
        removed: list[str] = []
        with patch(
            "workspace_gc_loop.run_subprocess",
            self._dispatch(worktrees=porcelain, removed=removed),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0
        assert removed == []

    @pytest.mark.asyncio
    async def test_list_failure_returns_zero(self, tmp_path: Path) -> None:
        loop, _s, _e = _make_loop(tmp_path)
        self._real_phase5(loop)
        with patch(
            "workspace_gc_loop.run_subprocess",
            new_callable=AsyncMock,
            side_effect=RuntimeError("git worktree list failed"),
        ):
            count = await loop._collect_orphaned_worktrees()
        assert count == 0

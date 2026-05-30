"""EpicMonitorLoop background worker coverage."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import make_bg_loop_deps


def _make_issue(
    number: int, *, state: str = "open", body: str = "", labels: list[str] | None = None
):
    from tests.conftest import IssueFactory

    return IssueFactory.create(
        number=number,
        title=f"Issue #{number}",
        body=body,
        labels=labels or [],
        state=state,
    )


def _make_epic(number: int, body: str, *, labels: list[str] | None = None):
    return _make_issue(number, body=body, labels=labels or ["hydraflow-epic"])


def _make_loop(tmp_path: Path, *, enabled: bool = True, interval: int = 60):
    from epic_monitor_loop import EpicMonitorLoop

    deps = make_bg_loop_deps(tmp_path, enabled=enabled, epic_monitor_interval=interval)

    epic_manager = MagicMock()
    epic_manager.check_stale_epics = AsyncMock(return_value=[])
    epic_manager.sweep_completed_epics = AsyncMock(
        return_value={"checked": 0, "swept": 0, "total_open_epics": 0}
    )
    epic_manager.refresh_cache = AsyncMock(return_value=None)
    epic_manager.get_all_progress = MagicMock(return_value=[])

    loop = EpicMonitorLoop(
        config=deps.config,
        epic_manager=epic_manager,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, epic_manager


def _make_real_loop(tmp_path: Path, *, enabled: bool = True):
    from epic import EpicManager
    from epic_monitor_loop import EpicMonitorLoop

    deps = make_bg_loop_deps(tmp_path, enabled=enabled, epic_monitor_interval=60)

    fetcher = MagicMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

    prs = MagicMock()
    prs.update_issue_body = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    state = MagicMock()
    state.get_epic_state = MagicMock(return_value=None)
    state.close_epic = MagicMock()

    manager = EpicManager(
        config=deps.config,
        state=state,
        prs=prs,
        fetcher=fetcher,
        event_bus=deps.bus,
    )
    manager.check_stale_epics = AsyncMock(return_value=[])
    manager.refresh_cache = AsyncMock(return_value=None)
    manager.get_all_progress = MagicMock(return_value=[])

    loop = EpicMonitorLoop(
        config=deps.config,
        epic_manager=manager,
        deps=deps.loop_deps,
    )
    return loop, manager, fetcher, prs, state


class TestEpicMonitorLoop:
    @pytest.mark.asyncio
    async def test_do_work_calls_manager(self, tmp_path: Path) -> None:
        loop, _, mgr = _make_loop(tmp_path)
        await loop.run()

        mgr.check_stale_epics.assert_called()
        mgr.sweep_completed_epics.assert_called()
        mgr.refresh_cache.assert_called()
        mgr.get_all_progress.assert_called()

    @pytest.mark.asyncio
    async def test_returns_stale_count(self, tmp_path: Path) -> None:
        loop, _, mgr = _make_loop(tmp_path)
        mgr.check_stale_epics = AsyncMock(return_value=[100, 200])
        mgr.sweep_completed_epics = AsyncMock(
            return_value={"checked": 4, "swept": 1, "total_open_epics": 5}
        )
        mgr.refresh_cache = AsyncMock(return_value=None)
        mgr.get_all_progress = MagicMock(
            return_value=[MagicMock(), MagicMock(), MagicMock()]
        )

        result = await loop._do_work()
        assert result == {
            "stale_count": 2,
            "tracked_epics": 3,
            "checked": 4,
            "swept": 1,
            "total_open_epics": 5,
        }

    @pytest.mark.asyncio
    async def test_disabled_skips_work(self, tmp_path: Path) -> None:
        loop, _, mgr = _make_loop(tmp_path, enabled=False)
        await loop.run()

        mgr.check_stale_epics.assert_not_called()

    @pytest.mark.asyncio
    async def test_manager_error_propagates(self, tmp_path: Path) -> None:
        """A raise from the EpicManager must propagate out of ``_do_work`` so the
        BaseBackgroundLoop supervisor handles it — the loop must not silently
        swallow manager failures (#8771)."""
        loop, _, mgr = _make_loop(tmp_path)
        mgr.check_stale_epics = AsyncMock(side_effect=RuntimeError("github boom"))

        with pytest.raises(RuntimeError, match="github boom"):
            await loop._do_work()

    def test_default_interval(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900

    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path)
        assert loop._worker_name == "epic_monitor"


class TestEpicMonitorSweepParsing:
    def test_collects_from_body_checkboxes(self, tmp_path: Path) -> None:
        _, manager, *_ = _make_real_loop(tmp_path)
        body = "- [ ] #10 — Feature A\n- [x] #20 — Feature B\n- [ ] #30 — Feature C"
        refs = manager._collect_sweep_sub_issues(1, body)
        assert refs == [10, 20, 30]

    def test_collects_from_epic_state(self, tmp_path: Path) -> None:
        _, manager, _, _, state = _make_real_loop(tmp_path)
        from models import EpicState

        epic_state = EpicState(epic_number=1, title="Test", child_issues=[5, 15])
        state.get_epic_state = MagicMock(return_value=epic_state)
        refs = manager._collect_sweep_sub_issues(1, "")
        assert refs == [5, 15]

    def test_merges_body_and_state_deduped(self, tmp_path: Path) -> None:
        _, manager, _, _, state = _make_real_loop(tmp_path)
        from models import EpicState

        epic_state = EpicState(epic_number=1, title="Test", child_issues=[10, 25])
        state.get_epic_state = MagicMock(return_value=epic_state)
        body = "- [ ] #10 — overlapping\n- [ ] #30 — new"
        refs = manager._collect_sweep_sub_issues(1, body)
        assert refs == [10, 25, 30]

    def test_no_refs_returns_empty(self, tmp_path: Path) -> None:
        _, manager, *_ = _make_real_loop(tmp_path)
        refs = manager._collect_sweep_sub_issues(1, "No issue refs here")
        assert refs == []


class TestEpicMonitorSweepClosure:
    @pytest.mark.asyncio
    async def test_no_epics_returns_zeros(self, tmp_path: Path) -> None:
        loop, _, fetcher, *_ = _make_real_loop(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])

        result = await loop._do_work()

        assert result is not None
        assert result["checked"] == 0
        assert result["swept"] == 0
        assert result["total_open_epics"] == 0

    @pytest.mark.asyncio
    async def test_all_closed_sweeps_epic(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, state = _make_real_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10\n- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: _make_issue(n, state="closed")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["swept"] == 1
        prs.close_issue.assert_called_once_with(100)
        prs.post_comment.assert_called_once()
        state.close_epic.assert_called_once_with(100)
        assert "2 sub-issues" in prs.post_comment.call_args[0][1]

    @pytest.mark.asyncio
    async def test_partial_closed_skips(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10\n- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])

        def side_effect(n: int):
            if n == 10:
                return _make_issue(10, state="closed")
            return _make_issue(20, state="open")

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=side_effect)

        result = await loop._do_work()

        assert result is not None
        assert result["swept"] == 0
        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_sub_issue_skips(self, tmp_path: Path, caplog) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10\n- [ ] #999")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])

        def side_effect(n: int):
            if n == 10:
                return _make_issue(10, state="closed")
            return None

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=side_effect)
        with caplog.at_level(logging.WARNING, logger="hydraflow.epic"):
            result = await loop._do_work()

        assert result is not None
        assert result["swept"] == 0
        prs.close_issue.assert_not_called()
        assert any(
            "999" in r.message and r.levelno == logging.WARNING for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_updates_checkboxes_on_close(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        body = "- [ ] #10 — A\n- [ ] #20 — B"
        epic = _make_epic(100, body)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: _make_issue(n, state="closed")
        )

        await loop._do_work()

        prs.update_issue_body.assert_called_once_with(
            100, "- [x] #10 — A\n- [x] #20 — B"
        )

    @pytest.mark.asyncio
    async def test_skips_body_update_when_already_checked(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        body = "- [x] #10 — A\n- [x] #20 — B"
        epic = _make_epic(100, body)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: _make_issue(n, state="closed")
        )

        await loop._do_work()

        prs.update_issue_body.assert_not_called()

    @pytest.mark.asyncio
    async def test_adds_fixed_label_on_close(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic = _make_epic(100, "- [ ] #10")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: _make_issue(n, state="closed")
        )

        await loop._do_work()

        prs.add_labels.assert_called_once()
        assert "hydraflow-fixed" in prs.add_labels.call_args[0][1]

    @pytest.mark.asyncio
    async def test_sweeps_multiple_completed_epics(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic1 = _make_epic(100, "- [ ] #10")
        epic2 = _make_epic(200, "- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic1, epic2])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: _make_issue(n, state="closed")
        )

        result = await loop._do_work()

        assert result is not None
        assert result["swept"] == 2
        assert result["checked"] == 2
        assert prs.close_issue.call_count == 2

    @pytest.mark.asyncio
    async def test_epics_without_refs_not_checked(self, tmp_path: Path) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic = _make_epic(100, "Just a description with no issue refs")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic])

        result = await loop._do_work()

        assert result is not None
        assert result["checked"] == 0
        assert result["swept"] == 0
        assert result["total_open_epics"] == 1
        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_on_one_epic_does_not_abort_others(
        self, tmp_path: Path
    ) -> None:
        loop, _, fetcher, prs, _ = _make_real_loop(tmp_path)
        epic1 = _make_epic(100, "- [ ] #10")
        epic2 = _make_epic(200, "- [ ] #20")
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[epic1, epic2])

        async def side_effect(n: int):
            if n == 10:
                raise RuntimeError("transient network error")
            return _make_issue(n, state="closed")

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=side_effect)

        result = await loop._do_work()

        assert result is not None
        assert result["swept"] == 1
        assert result["checked"] == 2
        prs.close_issue.assert_called_once_with(200)

"""Regression-rot classification matrix hosted in StaleIssueLoop (#9597).

P10.6: covers the full closed+red / open+stale / open+fresh matrix end to
end through ``StaleIssueLoop._do_work()`` — not just the pure engine — plus
the blocked-annotation exemption, dedup (one rollup issue, not one per
finding), auto-resolve on recovery, and the kill-switch short-circuit.

Deliberately NOT filed under ``tests/regressions/test_issue_9597.py``: this
is a feature addition, not a bug fix, and a RED regression file named after
this issue would be immediately self-flagged by the very detector it adds.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from stale_issue_loop import StaleIssueLoop
from state import StateTracker

HELD_BACK = (
    "import pytest\n\n"
    "@pytest.mark.xfail(reason='Regression for issue #{n} — fix not yet "
    "landed', strict=False)\n"
    "def test_thing():\n"
    "    assert False\n"
)

BLOCKED = "# hydraflow-regression-rot: blocked-on #9080\n" + HELD_BACK

GREEN = "def test_thing():\n    assert True\n"


def _write_regression(repo_root: Path, filename: str, body: str) -> None:
    regressions = repo_root / "tests" / "regressions"
    regressions.mkdir(parents=True, exist_ok=True)
    (regressions / filename).write_text(body, encoding="utf-8")


def _deps(*, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _make_loop(
    tmp_path: Path, *, enabled: bool = True
) -> tuple[StaleIssueLoop, MagicMock, StateTracker]:
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="owner/repo",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

    prs = MagicMock()
    prs._repo = "owner/repo"
    prs._run_gh = AsyncMock(return_value=json.dumps([]))
    prs.post_comment = AsyncMock()
    prs.get_issue_state = AsyncMock(return_value="UNKNOWN")
    prs.create_issue = AsyncMock(return_value=555)
    prs.update_issue_body = AsyncMock()
    prs.close_issue = AsyncMock()

    state = StateTracker(state_file=tmp_path / "data" / "state.json")

    loop = StaleIssueLoop(
        config=config, prs=prs, state=state, deps=_deps(enabled=enabled)
    )
    return loop, prs, state


class TestNoRegressionsDirIsANoOp:
    @pytest.mark.asyncio
    async def test_missing_dir_makes_no_issue_state_calls(self, tmp_path: Path) -> None:
        """No `tests/regressions/` dir -> the subsystem never touches PRPort."""
        loop, prs, _ = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result == {"scanned": 0, "closed": 0, "skipped": 0}
        prs.get_issue_state.assert_not_called()
        prs.create_issue.assert_not_called()


class TestClosedAndRedIsFalseCloseRot:
    @pytest.mark.asyncio
    async def test_closed_issue_with_red_pin_files_rollup(self, tmp_path: Path) -> None:
        _write_regression(
            tmp_path / "repo", "test_issue_100.py", HELD_BACK.format(n=100)
        )
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        result = await loop._do_work()

        assert result["regression_rot_false_close"] == 1
        assert result["regression_rot_orphaned"] == 0
        prs.create_issue.assert_awaited_once()
        title, body, labels = prs.create_issue.await_args.args
        assert "Regression-test rot" in title
        assert "#100" in body
        assert labels  # find_label applied


class TestOpenAndStaleIsOrphanedRed:
    @pytest.mark.asyncio
    async def test_open_issue_red_past_threshold_files_rollup(
        self, tmp_path: Path
    ) -> None:
        _write_regression(
            tmp_path / "repo", "test_issue_200.py", HELD_BACK.format(n=200)
        )
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="OPEN")

        # Seed the first-seen clock in the past so it's already stale.
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        loop._regression_rot_timestamps.set_if_absent(200, old)

        result = await loop._do_work()

        assert result["regression_rot_orphaned"] == 1
        assert result["regression_rot_false_close"] == 0
        prs.create_issue.assert_awaited_once()
        _, body, _ = prs.create_issue.await_args.args
        assert "#200" in body


class TestOpenAndFreshYieldsNoFinding:
    @pytest.mark.asyncio
    async def test_freshly_red_open_issue_files_nothing(self, tmp_path: Path) -> None:
        """First tick observing an OPEN+RED issue: age is 0 days, well under
        the default 14-day threshold -> no finding yet."""
        _write_regression(
            tmp_path / "repo", "test_issue_300.py", HELD_BACK.format(n=300)
        )
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="OPEN")

        result = await loop._do_work()

        assert result["regression_rot_orphaned"] == 0
        assert result["regression_rot_false_close"] == 0
        prs.create_issue.assert_not_called()
        # But the clock has started for this issue.
        assert loop._regression_rot_timestamps.get(300) is not None


class TestBlockedAnnotationExempts:
    @pytest.mark.asyncio
    async def test_blocked_annotation_exempts_even_when_closed(
        self, tmp_path: Path
    ) -> None:
        _write_regression(tmp_path / "repo", "test_issue_400.py", BLOCKED.format(n=400))
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        result = await loop._do_work()

        assert result["regression_rot_false_close"] == 0
        assert result["regression_rot_orphaned"] == 0
        prs.get_issue_state.assert_not_called()  # blocked files aren't even resolved
        prs.create_issue.assert_not_called()


class TestGreenFileNeverClassified:
    @pytest.mark.asyncio
    async def test_green_regression_file_is_ignored(self, tmp_path: Path) -> None:
        _write_regression(tmp_path / "repo", "test_issue_500.py", GREEN)
        loop, prs, _ = _make_loop(tmp_path)

        result = await loop._do_work()

        assert result["regression_rot_false_close"] == 0
        assert result["regression_rot_orphaned"] == 0
        prs.get_issue_state.assert_not_called()
        prs.create_issue.assert_not_called()


class TestDedupAndResolve:
    @pytest.mark.asyncio
    async def test_second_tick_same_finding_does_not_recreate_issue(
        self, tmp_path: Path
    ) -> None:
        _write_regression(
            tmp_path / "repo", "test_issue_600.py", HELD_BACK.format(n=600)
        )
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        await loop._do_work()
        await loop._do_work()

        prs.create_issue.assert_awaited_once()
        prs.update_issue_body.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recovery_closes_the_rollup_issue(self, tmp_path: Path) -> None:
        regressions_dir = tmp_path / "repo"
        _write_regression(regressions_dir, "test_issue_700.py", HELD_BACK.format(n=700))
        loop, prs, _ = _make_loop(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        await loop._do_work()
        prs.create_issue.assert_awaited_once()

        # Fix lands: the file no longer carries the xfail marker.
        _write_regression(regressions_dir, "test_issue_700.py", GREEN)
        await loop._do_work()

        prs.close_issue.assert_awaited_once_with(555)


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_disabled_makes_no_regression_rot_calls(self, tmp_path: Path) -> None:
        _write_regression(
            tmp_path / "repo", "test_issue_800.py", HELD_BACK.format(n=800)
        )
        loop, prs, _ = _make_loop(tmp_path, enabled=False)

        result = await loop._do_work()

        assert result == {"status": "disabled"}
        prs.get_issue_state.assert_not_called()
        prs.create_issue.assert_not_called()

"""Tests for the CIMonitorLoop background worker."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ci_monitor_loop import CIMonitorLoop
from events import EventType
from models import CIMonitorSettings
from tests.helpers import make_bg_loop_deps


def _make_run(
    name: str,
    conclusion: str,
    run_id: int = 100,
    html_url: str = "https://github.com/o/r/actions/runs/100",
) -> dict[str, Any]:
    """Build a minimal workflow run dict."""
    return {
        "name": name,
        "conclusion": conclusion,
        "id": run_id,
        "html_url": html_url,
    }


def _make_state(
    *,
    branch: str = "main",
    workflows: list[str] | None = None,
    create_issue: bool = True,
    tracked_failures: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with CI monitor methods."""
    state = MagicMock()
    settings = CIMonitorSettings(
        branch=branch,
        workflows=workflows or [],
        create_issue=create_issue,
    )
    state.get_ci_monitor_settings.return_value = settings
    state.get_ci_monitor_tracked_failures.return_value = dict(tracked_failures or {})
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 1800,
    runs: list[dict[str, Any]] | None = None,
    branch: str = "main",
    workflows: list[str] | None = None,
    create_issue: bool = True,
    tracked_failures: dict[str, str] | None = None,
    existing_issues: list[dict[str, Any]] | None = None,
) -> tuple[CIMonitorLoop, MagicMock, MagicMock]:
    """Build a CIMonitorLoop with test-friendly defaults.

    Returns (loop, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, ci_monitor_interval=interval)

    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=42)

    state = _make_state(
        branch=branch,
        workflows=workflows,
        create_issue=create_issue,
        tracked_failures=tracked_failures,
    )

    loop = CIMonitorLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )

    # Patch _fetch_runs to return the test data
    loop._fetch_runs = AsyncMock(return_value=runs or [])

    # Patch _has_open_ci_fix_issue
    if existing_issues is not None:
        # If specific issues provided, check if any match
        async def _check_existing(workflow: str, branch: str) -> bool:
            return any(
                issue.get("title", "").startswith(f"[CI Fix] {workflow}")
                for issue in existing_issues
            )

        loop._has_open_ci_fix_issue = AsyncMock(side_effect=_check_existing)
    else:
        loop._has_open_ci_fix_issue = AsyncMock(return_value=False)

    return loop, prs, state


class TestCIMonitorLoopInterval:
    """Tests for interval configuration."""

    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        loop, *_ = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900


class TestCIMonitorLoopDoWork:
    """Tests for _do_work — the core CI monitoring logic."""

    @pytest.mark.asyncio
    async def test_no_failing_workflows_returns_zeroes(self, tmp_path: Path) -> None:
        """When no workflows are failing, all counters are zero."""
        loop, prs, _ = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "success")],
        )
        result = await loop._do_work()
        assert result == {
            "workflows_checked": 1,
            "failures_detected": 0,
            "issues_created": 0,
            "recovered": 0,
        }
        prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_runs_returns_zeroes(self, tmp_path: Path) -> None:
        """When there are no runs at all, all counters are zero."""
        loop, prs, _ = _make_loop(tmp_path, runs=[])
        result = await loop._do_work()
        assert result == {
            "workflows_checked": 0,
            "failures_detected": 0,
            "issues_created": 0,
            "recovered": 0,
        }

    @pytest.mark.asyncio
    async def test_failing_workflow_creates_issue(self, tmp_path: Path) -> None:
        """A failing workflow creates a GitHub issue with hydraflow-find label."""
        loop, prs, state = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "failure", run_id=200)],
        )

        result = await loop._do_work()

        assert result["failures_detected"] == 1
        assert result["issues_created"] == 1
        prs.create_issue.assert_awaited_once()
        call_args = prs.create_issue.call_args
        title = call_args[0][0]
        body = call_args[0][1]
        labels = call_args[0][2]
        assert "[CI Fix]" in title
        assert "CI" in title
        assert "main" in title
        assert "hydraflow-find" in labels
        assert "200" in body

        # Should persist tracked failure
        state.set_ci_monitor_tracked_failures.assert_called_once()
        tracked = state.set_ci_monitor_tracked_failures.call_args[0][0]
        assert tracked["CI"] == "200"

    @pytest.mark.asyncio
    async def test_already_tracked_failure_skips(self, tmp_path: Path) -> None:
        """A workflow already tracked as failed is not re-reported."""
        loop, prs, _ = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "failure", run_id=200)],
            tracked_failures={"CI": "100"},
        )

        result = await loop._do_work()

        assert result["failures_detected"] == 0
        assert result["issues_created"] == 0
        prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_open_ci_fix_issue_skips(self, tmp_path: Path) -> None:
        """If an open [CI Fix] issue already exists, no new issue is created."""
        loop, prs, state = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "failure", run_id=200)],
            existing_issues=[{"number": 10, "title": "[CI Fix] CI failing on main"}],
        )

        result = await loop._do_work()

        assert result["failures_detected"] == 1
        assert result["issues_created"] == 0
        prs.create_issue.assert_not_awaited()

        # Should still track the failure
        state.set_ci_monitor_tracked_failures.assert_called_once()
        tracked = state.set_ci_monitor_tracked_failures.call_args[0][0]
        assert "CI" in tracked

    @pytest.mark.asyncio
    async def test_workflow_recovers_clears_tracked(self, tmp_path: Path) -> None:
        """A workflow that was failing but now succeeds is cleared from tracking."""
        loop, prs, state = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "success")],
            tracked_failures={"CI": "100"},
        )

        result = await loop._do_work()

        assert result["recovered"] == 1
        state.set_ci_monitor_tracked_failures.assert_called_once()
        tracked = state.set_ci_monitor_tracked_failures.call_args[0][0]
        assert "CI" not in tracked

    @pytest.mark.asyncio
    async def test_create_issue_false_logs_but_no_issue(self, tmp_path: Path) -> None:
        """When create_issue=False, failures are tracked but no issue created."""
        loop, prs, state = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "failure", run_id=200)],
            create_issue=False,
        )

        result = await loop._do_work()

        assert result["failures_detected"] == 1
        assert result["issues_created"] == 0
        prs.create_issue.assert_not_awaited()

        # Should still track the failure
        state.set_ci_monitor_tracked_failures.assert_called_once()
        tracked = state.set_ci_monitor_tracked_failures.call_args[0][0]
        assert "CI" in tracked

    @pytest.mark.asyncio
    async def test_multiple_workflows_mixed_status(self, tmp_path: Path) -> None:
        """Multiple workflows: some failing, some passing, some recovering."""
        loop, prs, state = _make_loop(
            tmp_path,
            runs=[
                _make_run("lint", "failure", run_id=301),
                _make_run("test", "success", run_id=302),
                _make_run("deploy", "failure", run_id=303),
            ],
            tracked_failures={"test": "200"},
        )

        result = await loop._do_work()

        assert result["workflows_checked"] == 3
        assert result["failures_detected"] == 2
        assert result["issues_created"] == 2
        assert result["recovered"] == 1
        assert prs.create_issue.await_count == 2

    @pytest.mark.asyncio
    async def test_workflow_filter_applied(self, tmp_path: Path) -> None:
        """Only workflows in the settings filter are checked."""
        loop, prs, _ = _make_loop(
            tmp_path,
            runs=[
                _make_run("CI", "failure", run_id=400),
                _make_run("deploy", "failure", run_id=401),
            ],
            workflows=["CI"],
        )

        result = await loop._do_work()

        # Only CI should be checked (deploy filtered out)
        assert result["workflows_checked"] == 1
        assert result["failures_detected"] == 1
        assert result["issues_created"] == 1

    @pytest.mark.asyncio
    async def test_sentry_breadcrumb_recorded(self, tmp_path: Path) -> None:
        """Sentry breadcrumb is recorded after check completes."""
        loop, *_ = _make_loop(
            tmp_path,
            runs=[_make_run("CI", "success")],
        )

        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            await loop._do_work()

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "ci_monitor.check_completed"
        assert call_kwargs["data"]["workflows_checked"] == 1

    @pytest.mark.asyncio
    async def test_groups_by_workflow_keeps_first(self, tmp_path: Path) -> None:
        """When multiple runs exist for the same workflow, the first (most recent) wins."""
        loop, prs, _ = _make_loop(
            tmp_path,
            runs=[
                _make_run("CI", "failure", run_id=500),
                _make_run("CI", "success", run_id=499),
            ],
        )

        result = await loop._do_work()

        # First run is "failure", so it should detect failure
        assert result["workflows_checked"] == 1
        assert result["failures_detected"] == 1


class TestCIMonitorLoopRun:
    """Tests for the full run() lifecycle."""

    @pytest.mark.asyncio
    async def test_run_publishes_worker_status_event(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, *_ = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "ci_monitor"
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run_skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, *_ = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

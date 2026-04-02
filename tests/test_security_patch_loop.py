"""Tests for the SecurityPatchLoop background worker."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import SecurityPatchSettings
from security_patch_loop import SecurityPatchLoop
from tests.helpers import make_bg_loop_deps


def _make_alert(
    number: int,
    severity: str = "critical",
    *,
    fixed_at: str | None = None,
    state: str = "open",
) -> dict:
    """Build a minimal Dependabot alert dict."""
    return {
        "number": number,
        "security_advisory": {"severity": severity},
        "fixed_at": fixed_at,
        "state": state,
        "dependency": {
            "package": {"name": f"pkg-{number}", "ecosystem": "pip"},
        },
    }


def _make_state(
    *,
    severity_levels: list[str] | None = None,
    processed: set[str] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with security patch methods."""
    state = MagicMock()
    settings = SecurityPatchSettings(
        severity_levels=severity_levels or ["critical", "high"],
    )
    state.get_security_patch_settings.return_value = settings
    state.get_security_patch_processed.return_value = processed or set()
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    alerts: list[dict] | None = None,
    processed: set[str] | None = None,
    severity_levels: list[str] | None = None,
) -> tuple[SecurityPatchLoop, asyncio.Event, MagicMock, MagicMock]:
    """Build a SecurityPatchLoop with test-friendly defaults.

    Returns (loop, stop_event, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(
        tmp_path, enabled=enabled, security_patch_interval=interval
    )

    prs = MagicMock()
    # _run_gh returns JSON string for _fetch_alerts
    prs._run_gh = AsyncMock(return_value=json.dumps(alerts or []))
    prs.create_task = AsyncMock(return_value=999)

    state = _make_state(
        severity_levels=severity_levels,
        processed=processed,
    )

    loop = SecurityPatchLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )

    return loop, deps.stop_event, prs, state


class TestNoAlerts:
    @pytest.mark.asyncio
    async def test_no_alerts_returns_zeroes(self, tmp_path: Path) -> None:
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[])
        result = await loop._do_work()
        assert result == {"triggered": 0, "skipped": 0, "manual_issues": 0}


class TestAlertMatchingSeverity:
    @pytest.mark.asyncio
    async def test_matching_severity_triggers_fix(self, tmp_path: Path) -> None:
        alert = _make_alert(1, "critical")
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[alert])

        result = await loop._do_work()

        assert result is not None
        assert result["triggered"] == 1
        state.add_security_patch_processed.assert_called_once_with("1")


class TestAlertNotMatchingSeverity:
    @pytest.mark.asyncio
    async def test_non_matching_severity_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(1, "low")
        loop, stop, prs, state = _make_loop(
            tmp_path, alerts=[alert], severity_levels=["critical", "high"]
        )

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["triggered"] == 0
        state.add_security_patch_processed.assert_not_called()


class TestAlreadyProcessed:
    @pytest.mark.asyncio
    async def test_already_processed_alert_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(1, "critical")
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[alert], processed={"1"})

        result = await loop._do_work()

        assert result is not None
        assert result["triggered"] == 0
        assert result["skipped"] == 1


class TestExistingFixPR:
    @pytest.mark.asyncio
    async def test_alert_with_existing_fix_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(1, "critical", fixed_at="2026-01-01T00:00:00Z")
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[alert])

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["triggered"] == 0


class TestManualIssueCreation:
    @pytest.mark.asyncio
    async def test_manual_issue_created_on_comment_failure(
        self, tmp_path: Path
    ) -> None:
        alert = _make_alert(1, "critical")
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[alert])

        # Override _trigger_fix to indicate failure (Dependabot can't auto-fix)
        loop._trigger_fix = AsyncMock(return_value=False)  # type: ignore[method-assign]

        result = await loop._do_work()

        assert result is not None
        assert result["manual_issues"] == 1
        prs.create_task.assert_called_once()
        state.add_security_patch_processed.assert_called_once_with("1")


class TestSentryBreadcrumb:
    @pytest.mark.asyncio
    async def test_sentry_breadcrumb_emitted(self, tmp_path: Path) -> None:
        alert = _make_alert(1, "critical")
        loop, stop, prs, state = _make_loop(tmp_path, alerts=[alert])

        mock_sentry = MagicMock()
        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            await loop._do_work()

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "security_patch"


class TestDefaultInterval:
    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, *_ = _make_loop(tmp_path, interval=21600)
        assert loop._get_default_interval() == 21600

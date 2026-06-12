"""Tests for the SecurityPatchLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from security_patch_loop import SecurityPatchLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


class _FakeState:
    """In-memory ``RollupIssueManager`` state surface — mirrors RollupIssueStateMixin."""

    def __init__(self) -> None:
        self._rollups: dict[str, dict] = {}

    def get_rollup_issue(self, key: str) -> dict | None:
        entry = self._rollups.get(key)
        if not entry:
            return None
        return {
            "issue_number": int(entry["issue_number"]),
            "content_hash": str(entry["content_hash"]),
        }

    def set_rollup_issue(
        self, key: str, *, issue_number: int, content_hash: str
    ) -> None:
        self._rollups[key] = {
            "issue_number": int(issue_number),
            "content_hash": content_hash,
        }

    def clear_rollup_issue(self, key: str) -> None:
        self._rollups.pop(key, None)

    def get_rollup_issue_keys(self, namespace: str) -> list[str]:
        prefix = f"{namespace}:"
        return [k for k in self._rollups if k.startswith(prefix)]


def _make_alert(
    number: int,
    severity: str = "high",
    package: str = "lodash",
    summary: str = "Prototype Pollution",
    first_patched: str | None = "4.17.21",
) -> dict:
    """Build a minimal Dependabot alert dict."""
    vuln = {
        "package": {"name": package, "ecosystem": "npm"},
        "severity": severity,
        "first_patched_version": {"identifier": first_patched}
        if first_patched
        else None,
    }
    return {
        "number": number,
        "state": "open",
        "security_advisory": {"summary": summary},
        "security_vulnerability": vuln,
    }


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
    severity_threshold: str = "high",
    security_patch_interval: int = 3600,
    alerts: list[dict] | None = None,
    resolved_alerts: dict[str, list[dict]] | None = None,
    create_issue_return: int = 42,
) -> tuple[SecurityPatchLoop, AsyncMock, asyncio.Event]:
    """Build a SecurityPatchLoop with test-friendly defaults.

    ``alerts`` are returned for the ``open`` query; ``resolved_alerts`` maps a
    resolved state (``fixed`` / ``dismissed`` / ``auto_dismissed``) to the alerts
    returned for that query, so the recovery path can be exercised without the
    open query bleeding into the resolved reconcile.
    """
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        dry_run=dry_run,
        security_patch_interval=security_patch_interval,
        security_patch_severity_threshold=severity_threshold,
    )
    open_alerts = alerts or []
    resolved = resolved_alerts or {}

    async def _alerts_by_state(state: str = "open") -> list[dict]:
        if state == "open":
            return open_alerts
        return resolved.get(state, [])

    pr_manager = AsyncMock()
    pr_manager.get_dependabot_alerts = AsyncMock(side_effect=_alerts_by_state)
    pr_manager.create_issue = AsyncMock(return_value=create_issue_return)

    loop = SecurityPatchLoop(
        config=deps.config,
        pr_manager=pr_manager,
        state=_FakeState(),
        deps=deps.loop_deps,
    )
    return loop, pr_manager, deps.stop_event


# ===========================================================================
# Tests
# ===========================================================================


class TestSecurityPatchLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "security_patch"

    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path, security_patch_interval=7200)
        assert loop._get_default_interval() == 7200

    def test_default_interval_config_field(self) -> None:
        config = ConfigFactory.create(security_patch_interval=3600)
        assert config.security_patch_interval == 3600

    def test_severity_threshold_config_field(self) -> None:
        config = ConfigFactory.create(security_patch_severity_threshold="critical")
        assert config.security_patch_severity_threshold == "critical"


class TestSecurityPatchLoopWork:
    @pytest.mark.asyncio
    async def test_no_alerts_returns_zero(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path, alerts=[])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_fixable_alert_files_issue(self, tmp_path: Path) -> None:
        alert = _make_alert(
            1, severity="high", package="lodash", summary="Prototype Pollution"
        )
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1
        pm.create_issue.assert_called_once()
        # The rollup files via create_issue(title, body, labels) positionally.
        title, _body, labels = pm.create_issue.call_args[0]
        assert "[Security]" in title
        assert "lodash" in title
        assert "security" in labels
        # The issue number is now tracked so a later tick won't re-file.
        assert loop._state.get_rollup_issue("security_patch:1") is not None

    @pytest.mark.asyncio
    async def test_unfixable_alert_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(2, first_patched=None)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_unfixable"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_alert_not_refiled(self, tmp_path: Path) -> None:
        alert = _make_alert(1)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert])
        # Alert #1 already has a tracked open issue (filed on a prior tick).
        loop._state.set_rollup_issue(
            "security_patch:1", issue_number=42, content_hash="seed"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_dedup"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_github_issue_adopted_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        # Local rollup state is empty, but the issue already exists on GitHub —
        # create_issue's exact-title dedup returns the existing number (99).
        # ensure() adopts it into state; the next tick must NOT re-file.
        alert = _make_alert(1)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert], create_issue_return=99)
        await loop._do_work()
        await loop._do_work()
        pm.create_issue.assert_awaited_once()  # adopted, not duplicated
        tracked = loop._state.get_rollup_issue("security_patch:1")
        assert tracked is not None
        assert tracked["issue_number"] == 99

    @pytest.mark.asyncio
    async def test_severity_below_threshold_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(3, severity="low")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="high"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_severity"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        alert = _make_alert(1)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert], dry_run=True)
        result = await loop._do_work()
        assert result is None
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_medium_alert_passes_medium_threshold(self, tmp_path: Path) -> None:
        alert = _make_alert(4, severity="medium")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="medium"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1

    @pytest.mark.asyncio
    async def test_critical_alert_passes_high_threshold(self, tmp_path: Path) -> None:
        alert = _make_alert(5, severity="critical")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="high"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1


class TestSecurityPatchLoopRecovery:
    """#9359: close the security issue when GitHub reports the alert resolved."""

    @pytest.mark.asyncio
    async def test_fixed_alert_closes_tracked_issue(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(
            tmp_path,
            alerts=[],
            resolved_alerts={"fixed": [_make_alert(1)]},
        )
        loop._state.set_rollup_issue(
            "security_patch:1", issue_number=42, content_hash="seed"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["closed"] == 1
        pm.close_issue.assert_awaited_once_with(42)
        assert loop._state.get_rollup_issue("security_patch:1") is None

    @pytest.mark.asyncio
    async def test_dismissed_alert_closes_tracked_issue(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(
            tmp_path,
            alerts=[],
            resolved_alerts={"dismissed": [_make_alert(7)]},
        )
        loop._state.set_rollup_issue(
            "security_patch:7", issue_number=70, content_hash="seed"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["closed"] == 1
        pm.close_issue.assert_awaited_once_with(70)

    @pytest.mark.asyncio
    async def test_transient_empty_response_does_not_close(
        self, tmp_path: Path
    ) -> None:
        # The mass-close guard: a transient API error makes EVERY alert query
        # (open + resolved) return []. Nothing must be closed — only an
        # explicitly-resolved alert closes its issue.
        loop, pm, _stop = _make_loop(tmp_path, alerts=[], resolved_alerts={})
        loop._state.set_rollup_issue(
            "security_patch:1", issue_number=42, content_hash="seed"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["closed"] == 0
        pm.close_issue.assert_not_called()
        assert loop._state.get_rollup_issue("security_patch:1") is not None

    @pytest.mark.asyncio
    async def test_resolve_closes_only_the_resolved_alert(self, tmp_path: Path) -> None:
        # Alert #1 is fixed; alert #2 is still open. Only #1's issue closes.
        still_open = _make_alert(2, package="axios", summary="ReDoS")
        loop, pm, _stop = _make_loop(
            tmp_path,
            alerts=[still_open],
            resolved_alerts={"fixed": [_make_alert(1)]},
        )
        loop._state.set_rollup_issue(
            "security_patch:1", issue_number=42, content_hash="seed"
        )
        loop._state.set_rollup_issue(
            "security_patch:2", issue_number=43, content_hash="seed"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["closed"] == 1
        pm.close_issue.assert_awaited_once_with(42)
        # Alert #2 stays tracked + open.
        assert loop._state.get_rollup_issue("security_patch:2") is not None

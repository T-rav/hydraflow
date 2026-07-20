"""Regression: nothing noticed when the factory PROCESS itself was down (#10009).

Before this fix, an unresponsive/crashed HydraFlow process had no signal
outside itself (no external heartbeat) and no loud in-process signal on the
next boot (StagingPromotionLoop's cadence gate silently caught up, and no
boot-gap event ever reached the dashboard). Pins the two in-process halves
of the fix:

1. StagingPromotionLoop logs LOUDLY (not just a quiet catch-up cut) when its
   RC cadence was missed by a wide margin (> 1.5x rc_cadence_hours) —
   evidence the process was down, not just a routine late tick.
2. boot_gap_detector computes a SYSTEM_ALERT payload when the gap between
   the last persisted event and boot time crosses the configured threshold,
   so a silent multi-hour outage becomes a dashboard-visible "factory was
   down ~Xh" banner at the next boot.

The external watchdog half (scripts/factory_liveness_watchdog.py +
scripts/install_liveness_watchdog.py) is covered by its own dedicated test
files — it is a standalone script, not part of the ``src`` package, and
can't regress via an import-based pin here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from boot_gap_detector import compute_boot_gap_alert
from config import HydraFlowConfig
from events import EventBus
from staging_promotion_loop import StagingPromotionLoop


def _make_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StagingPromotionLoop:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_RC_CADENCE_HOURS", "4")
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
        # Keep this test focused on the cadence-boot-warning behaviour: the
        # CH-4 evidence-pack reconcile sweep shells out to real `gh` and is
        # unrelated to what's under test here.
        evidence_pack_enabled=False,
    )
    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:
        return None

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )
    prs = MagicMock()
    prs.find_open_promotion_pr = AsyncMock(return_value=None)
    prs.create_rc_branch = AsyncMock(return_value="sha123")
    prs.branch_has_diff_from_main = AsyncMock(return_value=True)
    prs.create_promotion_pr = AsyncMock(return_value=42)
    prs.push_synthetic_commit = AsyncMock(return_value="synthetic-sha")
    prs.list_rc_branches = AsyncMock(return_value=[])
    prs.delete_branch = AsyncMock(return_value=True)
    prs.wait_for_ci = AsyncMock(return_value=(True, "ok"))
    prs.merge_promotion_pr = AsyncMock(return_value=True)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.create_issue = AsyncMock(return_value=1234)
    return StagingPromotionLoop(config=cfg, prs=prs, deps=deps)


@pytest.mark.asyncio
async def test_wide_cadence_miss_logs_loudly_at_boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 4h-cadence loop last cut 30h ago (a plausible overnight outage
    window) must log a LOUD warning on its very first tick after boot, not
    just silently cut the overdue RC."""
    loop = _make_loop(tmp_path, monkeypatch)
    loop._record_last_rc(datetime.now(UTC) - timedelta(hours=30))

    with caplog.at_level(logging.WARNING, logger="hydraflow.staging_promotion_loop"):
        result = await loop._do_work()

    assert result["status"] == "opened"  # still cuts immediately
    assert any(
        "missed its RC cadence" in r.getMessage() and "likely down" in r.getMessage()
        for r in caplog.records
    )


def test_boot_gap_alert_fires_for_a_multi_hour_outage() -> None:
    """A 6-hour gap between the last persisted event and boot must produce a
    SYSTEM_ALERT payload the dashboard can render — silence is the bug."""
    boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    last_event_at = boot_at - timedelta(hours=6)

    alert = compute_boot_gap_alert(
        last_event_at=last_event_at, boot_at=boot_at, threshold_seconds=600
    )

    assert alert is not None
    assert "factory was down" in alert["message"]
    assert alert["source"] == "boot_gap_detector"


def test_boot_gap_alert_does_not_fire_on_a_normal_quick_restart() -> None:
    """A normal 2-minute deploy restart must NOT alert — only genuine
    downtime should surface, or the signal becomes noise operators ignore."""
    boot_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    last_event_at = boot_at - timedelta(minutes=2)

    alert = compute_boot_gap_alert(
        last_event_at=last_event_at, boot_at=boot_at, threshold_seconds=600
    )

    assert alert is None

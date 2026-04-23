"""Test HealthMonitor dead-man-switch for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps  # noqa: F401  (kept for parity with plan)
from config import HydraFlowConfig
from events import EventBus  # noqa: F401  (kept for parity with plan)
from health_monitor_loop import HealthMonitorLoop


@pytest.fixture
def hm_env(tmp_path: Path):
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        trust_fleet_sanity_interval=600,
    )
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {"trust_fleet_sanity": True}
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=17)
    # HealthMonitorLoop's full ctor wiring for _state + _bg_workers is landing
    # in a separate bead; inject attributes directly to exercise the
    # dead-man-switch path.
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    return hm, state, bg_workers, prs


async def test_stall_over_3x_interval_files_issue(hm_env) -> None:
    hm, state, _bg_workers, prs = hm_env
    # Sanity loop heartbeat is 4× interval old.
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": stale,
            "details": {},
        },
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_awaited_once()
    title = prs.create_issue.await_args.args[0]
    assert "sanity-loop-stalled" in title or "stalled" in title.lower()
    labels = prs.create_issue.await_args.args[2]
    assert "hydraflow-find" in labels
    assert "sanity-loop-stalled" in labels


async def test_no_issue_when_disabled(hm_env) -> None:
    hm, state, bg_workers, prs = hm_env
    bg_workers.worker_enabled = {"trust_fleet_sanity": False}
    stale = (datetime.now(UTC) - timedelta(seconds=99999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()


async def test_no_issue_when_heartbeat_recent(hm_env) -> None:
    hm, state, _bg_workers, prs = hm_env
    recent = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": recent, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()


async def test_no_issue_when_no_heartbeat_yet(hm_env) -> None:
    """A fresh install with no sanity-loop heartbeat must not trip."""
    hm, state, _bg_workers, prs = hm_env
    state.get_worker_heartbeats.return_value = {}
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()

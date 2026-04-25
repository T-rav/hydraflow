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
    from dedup_store import DedupStore

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
    # ``__new__`` bypasses the ctor; inject the attrs the dead-man-switch
    # uses directly. The real ctor sets all of these — see HealthMonitorLoop.
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    hm._sanity_stall_dedup = DedupStore(
        "hm_sanity_stall_test",
        tmp_path / "dedup" / "hm_sanity_stall_test.json",
    )
    hm._sanity_noop_streak = 0
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


async def test_dedup_prevents_repeated_issues_during_one_stall(hm_env) -> None:
    """Once a stall issue is filed, subsequent ticks must not refile."""
    hm, state, _bg_workers, prs = hm_env
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    # First tick files. Next two must not.
    await hm._check_sanity_loop_staleness()
    await hm._check_sanity_loop_staleness()
    await hm._check_sanity_loop_staleness()
    assert prs.create_issue.await_count == 1


async def test_recovery_clears_dedup_so_new_stall_files(hm_env) -> None:
    """When the loop recovers, dedup clears; a subsequent stall files fresh."""
    hm, state, _bg_workers, prs = hm_env
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert prs.create_issue.await_count == 1
    # Recovery — heartbeat inside threshold.
    recent = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": recent, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert prs.create_issue.await_count == 1  # no new file on recovery
    # New stall after recovery — must file again.
    stale2 = (datetime.now(UTC) - timedelta(seconds=3000)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale2, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert prs.create_issue.await_count == 2


@pytest.mark.asyncio
async def test_noop_streak_fires_when_heartbeat_fresh_but_workers_scanned_zero(
    hm_env,
) -> None:
    """G5: heartbeat is fresh but the loop is silently no-oping —
    workers_scanned == 0 across consecutive ticks must trip the
    activity-based dead-man-switch."""
    hm, state, _bg_workers, prs = hm_env
    recent = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    # workers_scanned is 0 — sanity loop ran but did nothing.
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 0},
        },
    }

    # First two calls: streak grows but stays under threshold (3).
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()
    assert hm._sanity_noop_streak == 1

    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()
    assert hm._sanity_noop_streak == 2

    # Third call: streak hits threshold, escalation files.
    await hm._check_sanity_loop_staleness()
    assert hm._sanity_noop_streak == 3
    prs.create_issue.assert_awaited_once()
    title = prs.create_issue.await_args.args[0]
    assert "ticked but did no work" in title


@pytest.mark.asyncio
async def test_noop_streak_resets_on_real_work(hm_env) -> None:
    """A non-zero workers_scanned tick clears the streak."""
    hm, state, _bg_workers, prs = hm_env
    recent = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 0},
        },
    }
    await hm._check_sanity_loop_staleness()
    await hm._check_sanity_loop_staleness()
    assert hm._sanity_noop_streak == 2

    # Real work happens — streak resets.
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 9},
        },
    }
    await hm._check_sanity_loop_staleness()
    assert hm._sanity_noop_streak == 0
    prs.create_issue.assert_not_awaited()

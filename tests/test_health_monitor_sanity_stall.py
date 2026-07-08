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
    bg_workers.run_started_at.return_value = None
    # Default: restart verb unavailable (unwired cb) — the dead-man-switch
    # falls through to filing immediately, preserving pre-restart behavior.
    bg_workers.restart = AsyncMock(return_value=False)
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=17)
    prs.list_issues_by_label = AsyncMock(return_value=[])
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


@pytest.mark.asyncio
async def test_recovery_closes_open_stall_issue(hm_env) -> None:
    """#9359: on recovery (real work again), the open sanity-loop-stalled issue
    is auto-closed via its label."""
    hm, state, _bg_workers, prs = hm_env
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert prs.create_issue.await_count == 1

    # Recovery — heartbeat fresh AND real work (workers_scanned > 0).
    recent = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 5},
        },
    }
    prs.list_issues_by_label = AsyncMock(
        return_value=[{"number": 91, "title": "x", "body": "", "updated_at": ""}]
    )
    await hm._check_sanity_loop_staleness()
    prs.close_issue.assert_awaited_once_with(91)


@pytest.mark.asyncio
async def test_stall_restart_first_defers_issue(hm_env) -> None:
    """Restart-first: when the restart verb succeeds, the first stall tick
    restarts the loop instead of paging a human."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    bg_workers.restart.assert_awaited_once_with("trust_fleet_sanity")
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_still_stale_after_restart_files_issue_once(hm_env) -> None:
    """A stall that survives its restart escalates — one issue, one restart."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()  # restart tick
    await hm._check_sanity_loop_staleness()  # still stale — file
    await hm._check_sanity_loop_staleness()  # dedup — no refile
    assert bg_workers.restart.await_count == 1
    assert prs.create_issue.await_count == 1
    body = prs.create_issue.await_args.args[1]
    assert "Auto-restart attempted" in body


@pytest.mark.asyncio
async def test_recovery_clears_restart_marker(hm_env) -> None:
    """Recovery clears the restart marker so a future stall restarts again."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert bg_workers.restart.await_count == 1
    # Recovery — fresh heartbeat with real work.
    recent = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 5},
        },
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()
    # New stall — restart fires again instead of escalating.
    stale2 = (datetime.now(UTC) - timedelta(seconds=3000)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale2, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    assert bg_workers.restart.await_count == 2
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_unavailable_files_immediately(hm_env) -> None:
    """When the restart verb is unwired (False), behavior matches the
    pre-restart contract: file on the first stall tick."""
    hm, state, bg_workers, prs = hm_env
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    bg_workers.restart.assert_awaited_once_with("trust_fleet_sanity")
    prs.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_young_sanity_task_with_stale_heartbeat_not_flagged(hm_env) -> None:
    """Post credit-pause: a just-recreated sanity task with a pre-pause
    heartbeat must not be restarted or escalated mid-first-cycle."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(seconds=30)
    stale = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_sanity_restart_once_contract_survives_young_task_window(
    hm_env,
) -> None:
    """The young-task window after a sanity restart must not clear
    _SANITY_RESTART_KEY — that would restart a broken sanity loop every
    threshold window forever instead of escalating once."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    stale = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()  # restart tick
    assert bg_workers.restart.await_count == 1
    # Recreated task's first cycle in flight — heartbeat still stale.
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(seconds=30)
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()
    # Task aged past threshold without heartbeating — escalate, not restart.
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(
        seconds=5_000
    )
    await hm._check_sanity_loop_staleness()
    assert bg_workers.restart.await_count == 1
    prs.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_noop_restart_marker_survives_streak_rebuild(hm_env) -> None:
    """After a noop-tripped restart, streak-rebuild ticks (workers_scanned=0,
    streak 1-2) must NOT clear the restart marker — the loop is no-oping,
    not recovered. Clearing there restarts a persistent no-op every 3 ticks
    forever with escalation permanently bypassed."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
    recent = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok",
            "last_run": recent,
            "details": {"workers_scanned": 0},
        },
    }
    for _ in range(3):
        await hm._check_sanity_loop_staleness()
    assert bg_workers.restart.await_count == 1  # noop restart fired
    prs.create_issue.assert_not_awaited()
    # Streak rebuilds (ticks 4-6); marker must survive so tick 6 escalates.
    for _ in range(3):
        await hm._check_sanity_loop_staleness()
    assert bg_workers.restart.await_count == 1  # no restart-thrash
    prs.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_noop_streak_also_restarts_first(hm_env) -> None:
    """The G5 no-op-streak stall variant gets the same restart-first path."""
    hm, state, bg_workers, prs = hm_env
    bg_workers.restart = AsyncMock(return_value=True)
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
    await hm._check_sanity_loop_staleness()  # streak hits 3 — restart, no issue
    bg_workers.restart.assert_awaited_once_with("trust_fleet_sanity")
    prs.create_issue.assert_not_awaited()

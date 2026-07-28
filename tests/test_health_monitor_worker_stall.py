"""Generic stall sweep: restart-first dead-man-switch for any registry loop.

The per-cycle watchdog (#9556) bounds a cycle that hangs; the supervisor
restarts a loop that raises. A loop that goes *silent* shows only as a stale
heartbeat — the sweep restarts it once per stall event and escalates with a
`loop-stalled` issue only when the restart didn't clear it (#9650).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from health_monitor_loop import HealthMonitorLoop


def _hb(age_seconds: int) -> dict:
    stamp = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return {"status": "ok", "last_run": stamp, "details": {}}


@pytest.fixture
def hm_env(tmp_path: Path):
    from dedup_store import DedupStore

    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.registered_loop_names.return_value = {"workspace_gc"}
    # interval 600s, watchdog bound 100s → threshold = 3×600 + 100 = 1900s
    bg_workers.get_interval.return_value = 600
    bg_workers.cycle_timeout.return_value = 100
    bg_workers.run_started_at.return_value = None
    bg_workers.restart = AsyncMock(return_value=True)
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=17)
    prs.list_issues_by_label = AsyncMock(return_value=[])
    bus = AsyncMock()
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    hm._bus = bus
    hm._worker_stall_dedup = DedupStore(
        "hm_worker_stall_test",
        tmp_path / "dedup" / "hm_worker_stall_test.json",
    )
    return hm, state, bg_workers, prs, bus


@pytest.mark.asyncio
async def test_healthy_loop_untouched(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(60)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_loop_restarted_not_escalated(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(2400)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("workspace_gc")
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_still_stale_after_restart_files_once(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(2400)}
    await hm._check_worker_staleness()  # restart tick
    await hm._check_worker_staleness()  # still stale — file
    await hm._check_worker_staleness()  # dedup — no refile
    assert bg_workers.restart.await_count == 1
    assert prs.create_issue.await_count == 1
    title, body, labels = prs.create_issue.await_args.args
    assert "workspace_gc" in title
    assert "loop-stalled" in title
    assert "Auto-restart attempted" in body
    assert "hydraflow-find" in labels
    assert "loop-stalled" in labels
    # Escalation publishes exactly one SYSTEM_ALERT (#10086) — the only
    # observable signal of a genuine escalation via the dashboard event feed.
    bus.publish.assert_awaited_once()
    (event,) = bus.publish.await_args.args
    assert event.data["kind"] == "worker_stall"
    assert event.data["source"] == "health_monitor"
    assert event.data["worker"] == "workspace_gc"
    assert event.data["issue"] == 17


@pytest.mark.asyncio
async def test_recovery_closes_own_issue_and_clears_markers(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(2400)}
    await hm._check_worker_staleness()  # restart
    await hm._check_worker_staleness()  # file
    assert prs.create_issue.await_count == 1
    # Recovery. Two open loop-stalled issues exist; only workspace_gc's
    # may be closed (title filter — the label is shared across loops).
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {"number": 91, "title": "loop-stalled: workspace_gc silent for 2400s"},
            {"number": 92, "title": "loop-stalled: repo_wiki silent for 9999s"},
        ]
    )
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(30)}
    await hm._check_worker_staleness()
    prs.close_issue.assert_awaited_once_with(91)
    # A fresh stall gets a fresh restart (markers cleared).
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(3000)}
    await hm._check_worker_staleness()
    assert bg_workers.restart.await_count == 2
    assert prs.create_issue.await_count == 1


@pytest.mark.asyncio
async def test_long_llm_cycle_bound_prevents_false_restart(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    # A LONG_LLM_CYCLE loop mid-cycle: heartbeat 2400s old but the loop's
    # watchdog bound is 4h — threshold 3×600+14400 = 16200s. Healthy.
    bg_workers.cycle_timeout.return_value = 14400
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(2400)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_worker_skipped(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.worker_enabled = {"workspace_gc": False}
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(99999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_trust_fleet_sanity_owned_by_specific_check(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"trust_fleet_sanity"}
    state.get_worker_heartbeats.return_value = {"trust_fleet_sanity": _hb(99999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_unregistered_worker_skipped(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"pipeline_poller": _hb(99999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_unavailable_files_immediately(hm_env) -> None:
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.restart = AsyncMock(return_value=False)
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(2400)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("workspace_gc")
    prs.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_close_does_not_match_prefix_sibling(hm_env) -> None:
    """`stale_issue` recovering must not close `stale_issue_gc`'s stall issue
    (nor clear its markers) — the registry's only prefix pair; a bare
    substring title match would hit both."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {
        "stale_issue",
        "stale_issue_gc",
    }
    hm._worker_stall_dedup.set_all(
        {
            "health_monitor:worker-stall:restart:stale_issue",
            "health_monitor:worker-stall:filed:stale_issue",
            "health_monitor:worker-stall:restart:stale_issue_gc",
            "health_monitor:worker-stall:filed:stale_issue_gc",
        }
    )
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 71,
                "title": "loop-stalled: stale_issue silent for 2400s (threshold 1900s)",
            },
            {
                "number": 72,
                "title": "loop-stalled: stale_issue_gc silent for 2400s "
                "(threshold 1900s)",
            },
        ]
    )
    state.get_worker_heartbeats.return_value = {
        "stale_issue": _hb(30),  # recovered
        "stale_issue_gc": _hb(99_999),  # still stalled
    }
    await hm._check_worker_staleness()
    closed = {c.args[0] for c in prs.close_issue.await_args_list}
    assert closed == {71}
    # The sibling's markers must survive its neighbor's recovery.
    keys = hm._worker_stall_dedup.get()
    assert "health_monitor:worker-stall:filed:stale_issue_gc" in keys
    assert "health_monitor:worker-stall:restart:stale_issue_gc" in keys


@pytest.mark.asyncio
async def test_health_monitor_never_self_restarts(hm_env) -> None:
    """The sweep runs inside health_monitor — self-cancelling mid-cycle
    (e.g. stale persisted heartbeat after long orchestrator downtime) is
    harm without benefit; a truly wedged health_monitor can't sweep anyway."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"health_monitor"}
    state.get_worker_heartbeats.return_value = {"health_monitor": _hb(99_999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_young_task_with_stale_heartbeat_not_restarted(hm_env) -> None:
    """Post credit-pause / orchestrator restart: the persisted heartbeat is
    stale but the current task was just created — heartbeats only refresh at
    cycle COMPLETION, so restarting here would cancel a healthy in-flight
    first cycle (wasted LLM spend) and could file false issues."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(seconds=30)
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(99_999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_task_with_stale_heartbeat_still_restarted(hm_env) -> None:
    """A task that has been running past the threshold without completing a
    cycle IS wedged — run_started_at must not mask genuine stalls."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(
        seconds=99_999
    )
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(99_999)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("workspace_gc")


@pytest.mark.asyncio
async def test_restart_once_contract_survives_young_task_window(hm_env) -> None:
    """The young-task window after a restart must NOT read as recovery:
    clearing the restart marker there turns 'restart once, then escalate'
    into 'restart forever, never escalate' for a genuinely wedged loop."""
    hm, state, bg_workers, prs, bus = hm_env
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(99_999)}
    await hm._check_worker_staleness()  # restart tick
    assert bg_workers.restart.await_count == 1
    # Recreated task's first cycle in flight — heartbeat still stale.
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(seconds=30)
    await hm._check_worker_staleness()
    assert bg_workers.restart.await_count == 1
    prs.create_issue.assert_not_awaited()
    assert (
        "health_monitor:worker-stall:restart:workspace_gc"
        in hm._worker_stall_dedup.get()
    )
    # Task aged past threshold without ever heartbeating — wedged for real.
    bg_workers.run_started_at.return_value = datetime.now(UTC) - timedelta(
        seconds=5_000
    )
    await hm._check_worker_staleness()
    assert bg_workers.restart.await_count == 1  # escalate, don't re-restart
    prs.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_deps_is_silent_noop(hm_env) -> None:
    hm, _state, bg_workers, prs, _bus = hm_env
    hm._bg_workers = None  # minimal scenario fixtures omit the injection
    await hm._check_worker_staleness()
    prs.create_issue.assert_not_awaited()


# --- Per-loop tight remediation multiplier (#10241) ------------------------
#
# Short-poll / long-cycle loops (staging_bisect: 600s poll, 7200s watchdog)
# opt into a tighter sweep multiplier so remediation fires closer to
# TrustFleetSanityLoop's own staleness alert (max(2xinterval, cycle_timeout)
# = 7200s) instead of ~30 min later at the blanket 3xinterval+cycle_timeout
# = 9000s window that left #10234 with nothing to act on.


def test_config_defaults_opt_in_staging_bisect() -> None:
    """staging_bisect and flake_tracker ship opted-in; tight multiplier is 2."""
    cfg = HydraFlowConfig(repo="hydra/hydraflow")
    assert cfg.worker_stall_tight_loops == ["staging_bisect", "flake_tracker"]
    assert cfg.worker_stall_tight_multiplier == 2


def test_multiplier_helper_tight_for_opt_in_blanket_otherwise(hm_env) -> None:
    hm, *_ = hm_env
    assert hm._worker_stall_multiplier("staging_bisect") == 2
    assert hm._worker_stall_multiplier("flake_tracker") == 2
    assert hm._worker_stall_multiplier("workspace_gc") == 3


@pytest.mark.asyncio
async def test_opt_in_loop_restarted_inside_the_alert_to_remediation_gap(
    hm_env,
) -> None:
    """staging_bisect hung at 8500s (past tight 8400s, inside blanket 9000s)
    is auto-restarted — the ~30-min gap #10241 closes."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"staging_bisect"}
    bg_workers.cycle_timeout.return_value = 7200  # 2h watchdog bound
    state.get_worker_heartbeats.return_value = {"staging_bisect": _hb(8500)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("staging_bisect")


@pytest.mark.asyncio
async def test_opt_in_legit_long_cycle_not_false_restarted(hm_env) -> None:
    """The tighter threshold (8400s) must still sit above the worst-case
    legitimate heartbeat age (interval + cycle_timeout = 7800s): a healthy
    max-length bisect cycle is not restarted."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"staging_bisect"}
    bg_workers.cycle_timeout.return_value = 7200
    state.get_worker_heartbeats.return_value = {"staging_bisect": _hb(7800)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()
    prs.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_opt_in_loop_keeps_blanket_window(hm_env) -> None:
    """Same shape, but not opted in: the blanket 9000s window still applies,
    so 8500s is not yet actionable — the tightening is scoped, not global."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"workspace_gc"}
    bg_workers.cycle_timeout.return_value = 7200
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(8500)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_filed_issue_body_reports_the_loops_own_multiplier(hm_env) -> None:
    """The escalation body must quote the multiplier actually used for the
    loop, not the blanket constant."""
    hm, state, bg_workers, prs, bus = hm_env
    bg_workers.registered_loop_names.return_value = {"staging_bisect"}
    bg_workers.cycle_timeout.return_value = 7200
    state.get_worker_heartbeats.return_value = {"staging_bisect": _hb(8500)}
    await hm._check_worker_staleness()  # restart tick
    await hm._check_worker_staleness()  # still stale — file
    prs.create_issue.assert_awaited_once()
    _title, body, _labels = prs.create_issue.await_args.args
    assert "2 × interval + cycle_timeout" in body
    assert "8400s" in body

"""Regression: #10652 — staging_bisect stall remediation must not lag the
TrustFleetSanityLoop staleness alert.

`TrustFleetSanityLoop` re-checks every ``trust_fleet_sanity_interval`` (600s)
and files a ``trust-loop-anomaly`` once ``staging_bisect``'s heartbeat crosses
its staleness threshold. The remediation half of that loop — the restart-first
stall sweep in ``HealthMonitorLoop._check_worker_staleness`` — used to run only
when the whole ``HealthMonitorLoop`` ticked, gated by the shared
``health_monitor_interval`` (7200s). That let the alert fire and be closed
several times over before remediation ever got a chance to run, so a genuine
stall churned for hours with no forward progress (see the 5-in-4-days
recurrence documented on the issue).

The fix decouples the stall sweep's cadence from the heavy ~9-check pass: the
loop now polls on a fast cadence aligned with the sanity loop's re-check
interval, and the heavy caretaker pass keeps its own 2h cadence behind an
elapsed-time gate. These tests are the acceptance oracle — they must pass
without weakening their assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from config import HydraFlowConfig
from dedup_store import DedupStore
from health_monitor_loop import HealthMonitorLoop


def _hb(age_seconds: int) -> dict:
    stamp = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return {"status": "ok", "last_run": stamp, "details": {}}


def _bare_hm(cfg: HydraFlowConfig) -> HealthMonitorLoop:
    """A ``__new__``-bypassed loop carrying only what these tests touch."""
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._worker_name = "health_monitor"
    return hm


def test_stall_sweep_cadence_aligned_with_sanity_alert() -> None:
    """The loop's poll cadence tracks the sanity loop's re-check interval, not
    the 7200s heavy-pass interval — so remediation can keep pace with the
    alert instead of trailing it by hours."""
    cfg = HydraFlowConfig(repo="hydra/hydraflow")
    hm = _bare_hm(cfg)

    interval = hm._get_default_interval()

    # Aligned with (or faster than) the sanity loop's own re-check cadence …
    assert interval <= cfg.trust_fleet_sanity_interval
    # … and strictly faster than the shared heavy-pass interval that used to
    # gate the sweep.
    assert interval < cfg.health_monitor_interval


def test_remediation_fires_on_a_sweep_only_cycle(tmp_path: Path) -> None:
    """On a fast tick that skips the heavy caretaker pass, the stall sweep must
    still restart a stalled ``staging_bisect`` — proving remediation no longer
    waits on the 7200s heavy cadence."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    hm = _bare_hm(cfg)
    hm._enabled_cb = lambda _name: True

    # Real sweep dependencies: staging_bisect is registered, enabled, and its
    # heartbeat is far past the tight-loop threshold (2×600 + 100 = 1300s).
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {"staging_bisect": _hb(5000)}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.registered_loop_names.return_value = {"staging_bisect"}
    bg_workers.get_interval.return_value = 600
    bg_workers.cycle_timeout.return_value = 100
    bg_workers.run_started_at.return_value = None
    bg_workers.restart = AsyncMock(return_value=True)
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=42)
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    hm._bus = AsyncMock()
    hm._worker_stall_dedup = DedupStore(
        "hm_worker_stall_10652",
        tmp_path / "dedup" / "hm_worker_stall_10652.json",
    )

    # The heavy caretaker pass is the expensive half; stub every member so a
    # sweep-only cycle would be observable if any of them ran.
    hm._check_sanity_loop_staleness = AsyncMock()
    hm._check_wiki_freshness = AsyncMock()
    hm._check_stale_code = AsyncMock()
    hm._check_event_loop_stall = AsyncMock()
    hm._check_persistent_worker_errors = AsyncMock()
    hm._run_log_ingestion_cycle = AsyncMock(return_value=None)
    hm._run_harness_auto_file_cycle = AsyncMock()
    hm._run_harness_suggestion_ingestion_cycle = AsyncMock()
    hm._file_hitl_recommendations = AsyncMock()

    # A heavy pass ran moments ago, so this tick must be sweep-only.
    hm._last_heavy_pass_ts = datetime.now(UTC)

    import asyncio

    result = asyncio.run(hm._do_work())

    # Remediation fired despite the heavy pass being skipped this cycle.
    bg_workers.restart.assert_awaited_once_with("staging_bisect")
    # None of the heavy caretaker checks ran on the sweep-only cycle.
    hm._check_wiki_freshness.assert_not_awaited()
    hm._check_stale_code.assert_not_awaited()
    hm._run_log_ingestion_cycle.assert_not_awaited()
    # The cycle reports itself as a sweep-only pass (not zeroed trend metrics).
    assert result is not None
    assert result.get("heavy_pass") is False


def test_heavy_pass_gate_boots_full_then_throttles_to_interval() -> None:
    """The heavy-pass gate runs on boot, throttles to one pass per
    ``health_monitor_interval`` thereafter, and re-opens once the interval has
    elapsed — so decoupling the sweep neither starves nor over-runs the ~9
    heavy caretaker checks."""
    cfg = HydraFlowConfig(repo="hydra/hydraflow")
    hm = _bare_hm(cfg)

    # Boot: no heavy pass recorded yet → run the full pass.
    hm._last_heavy_pass_ts = None
    assert hm._should_run_heavy_pass() is True

    # Just ran → throttled off on the next fast tick.
    hm._last_heavy_pass_ts = datetime.now(UTC)
    assert hm._should_run_heavy_pass() is False

    # A full interval later → due again.
    hm._last_heavy_pass_ts = datetime.now(UTC) - timedelta(
        seconds=cfg.health_monitor_interval + 1
    )
    assert hm._should_run_heavy_pass() is True

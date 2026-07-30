"""Regression for #10795: staleness-alert-to-auto-remediation gap for flake_tracker.

``TrustFleetSanityLoop`` alerts on a stale ``flake_tracker`` heartbeat at its own
staleness window — ``max(2 x interval, cycle_timeout)`` = ``max(28800, 7200)`` =
28800s. But the only *automated remediation* for a genuinely hung loop is
``HealthMonitorLoop``'s generic stall sweep, whose blanket threshold is
``_WORKER_STALL_MULTIPLIER (3) x interval + cycle_timeout`` = ``43200 + 7200`` =
50400s. That left a ~6h window (28800s -> 50400s) in which a trust-fleet
anomaly issue exists but the sweep has not even attempted a restart — the same
class of gap #10241 closed for ``staging_bisect`` (a short-poll/long-cycle
loop), except here it's an hours-scale poll interval (``interval >
cycle_timeout``) that produces the wide window instead of a short one.

The fix opts ``flake_tracker`` into the existing tight-sweep mechanism
(``worker_stall_tight_loops`` / ``worker_stall_tight_multiplier``, default 2),
dropping the threshold to ``2 x 14400 + 7200`` = 36000s, firing the
auto-restart ~1 interval past the trust alert instead of ~1.5. The multiplier
floor (ge=1) keeps the threshold strictly above the worst-case *legitimate*
heartbeat age (one pre-cycle interval + a full ``cycle_timeout`` = 21600s), so
a legitimately long in-flight cycle is still never false-restarted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from health_monitor_loop import HealthMonitorLoop

# flake_tracker shape: 14400s (4h) poll, 7200s (2h) per-cycle watchdog bound.
_INTERVAL_S = 14400
_CYCLE_TIMEOUT_S = 7200
# TrustFleetSanityLoop staleness alert (post-#10236): max(2 x interval, cycle).
_TRUST_ALERT_S = max(2 * _INTERVAL_S, _CYCLE_TIMEOUT_S)  # 28800
# Blanket sweep threshold: 3 x interval + cycle_timeout.
_BLANKET_SWEEP_S = 3 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 50400
# Tight sweep threshold (this fix): 2 x interval + cycle_timeout.
_TIGHT_SWEEP_S = 2 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 36000
# Worst-case legitimate heartbeat age: one pre-cycle sleep + a full watchdog.
_LEGIT_FLOOR_S = _INTERVAL_S + _CYCLE_TIMEOUT_S  # 21600


def _hb(age_seconds: int) -> dict:
    stamp = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return {"status": "ok", "last_run": stamp, "details": {}}


def _make_hm(tmp_path: Path, worker: str) -> tuple[HealthMonitorLoop, MagicMock, MagicMock]:
    from dedup_store import DedupStore

    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.registered_loop_names.return_value = {worker}
    bg_workers.get_interval.return_value = _INTERVAL_S
    bg_workers.cycle_timeout.return_value = _CYCLE_TIMEOUT_S
    bg_workers.run_started_at.return_value = None
    bg_workers.restart = AsyncMock(return_value=True)
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=42)
    prs.list_issues_by_label = AsyncMock(return_value=[])
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    hm._bus = AsyncMock()
    hm._worker_stall_dedup = DedupStore(
        "hm_10795_test",
        tmp_path / "dedup" / "hm_10795_test.json",
    )
    return hm, state, bg_workers


def test_threshold_arithmetic_documents_the_gap() -> None:
    """The trust alert precedes the blanket sweep by the whole gap the fix closes."""
    assert _TRUST_ALERT_S == 28800
    assert _BLANKET_SWEEP_S == 50400
    assert _TIGHT_SWEEP_S == 36000
    # The tight sweep fires strictly earlier than the blanket sweep...
    assert _TIGHT_SWEEP_S < _BLANKET_SWEEP_S
    # ...yet still strictly after the worst-case legitimate cycle age, so it
    # can never restart a healthy in-flight cycle.
    assert _TIGHT_SWEEP_S > _LEGIT_FLOOR_S


@pytest.mark.asyncio
async def test_flake_tracker_remediated_inside_the_gap(tmp_path: Path) -> None:
    """The core regression: a hung flake_tracker is auto-restarted at 39191s.

    39191s is the elapsed_s observed on the live #10795 escalation — past the
    tight threshold (36000s) but *inside* the old blanket window (50400s),
    precisely the gap where the trust-fleet alert had fired with nothing yet
    remediating.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "flake_tracker")
    elapsed = 39191
    assert _TIGHT_SWEEP_S < elapsed < _BLANKET_SWEEP_S
    state.get_worker_heartbeats.return_value = {"flake_tracker": _hb(elapsed)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("flake_tracker")


@pytest.mark.asyncio
async def test_legitimate_long_cycle_not_false_restarted(tmp_path: Path) -> None:
    """A healthy max-length flake_tracker cycle (elapsed at the legit floor)
    is spared.

    21600s = interval + cycle_timeout is the longest a healthy cycle can leave
    the heartbeat stale (the watchdog cancels any cycle at cycle_timeout). It
    sits below the tight threshold, so the sweep does not restart it.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "flake_tracker")
    assert _LEGIT_FLOOR_S < _TIGHT_SWEEP_S
    state.get_worker_heartbeats.return_value = {
        "flake_tracker": _hb(_LEGIT_FLOOR_S)
    }
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()

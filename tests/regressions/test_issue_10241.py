"""Regression for #10241: staleness-alert-to-auto-remediation gap for staging_bisect.

``TrustFleetSanityLoop`` alerts on a stale ``staging_bisect`` heartbeat at its
own staleness window — ``max(2 x interval, cycle_timeout)`` = ``max(1200, 7200)``
= 7200s after #10236. But the only *automated remediation* for a genuinely hung
loop is ``HealthMonitorLoop``'s generic stall sweep, whose blanket threshold is
``_WORKER_STALL_MULTIPLIER (3) x interval + cycle_timeout`` = ``1800 + 7200`` =
9000s. That left a ~30-min window (7200s -> 9000s) in which a trust-fleet anomaly
issue exists but the sweep has not even attempted a restart — the gap #10234
fell into.

The fix lets short-poll / long-cycle loops opt into a tighter sweep multiplier
(``worker_stall_tight_loops`` / ``worker_stall_tight_multiplier``, default 2),
so the threshold drops to ``2 x 600 + 7200`` = 8400s, firing the auto-restart
~1 interval past the trust alert instead of ~3. The multiplier floor (ge=1)
keeps the threshold strictly above the worst-case *legitimate* heartbeat age
(one pre-cycle interval + a full ``cycle_timeout`` = 7800s), so a legitimately
long in-flight bisect cycle is still never false-restarted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from health_monitor_loop import HealthMonitorLoop

# staging_bisect shape: 600s poll, 7200s per-cycle watchdog bound.
_INTERVAL_S = 600
_CYCLE_TIMEOUT_S = 7200
# TrustFleetSanityLoop staleness alert (post-#10236): max(2 x interval, cycle).
_TRUST_ALERT_S = max(2 * _INTERVAL_S, _CYCLE_TIMEOUT_S)  # 7200
# Blanket sweep threshold: 3 x interval + cycle_timeout.
_BLANKET_SWEEP_S = 3 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 9000
# Tight sweep threshold (this fix): 2 x interval + cycle_timeout.
_TIGHT_SWEEP_S = 2 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 8400
# Worst-case legitimate heartbeat age: one pre-cycle sleep + a full watchdog.
_LEGIT_FLOOR_S = _INTERVAL_S + _CYCLE_TIMEOUT_S  # 7800


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
        "hm_10241_test",
        tmp_path / "dedup" / "hm_10241_test.json",
    )
    return hm, state, bg_workers


def test_threshold_arithmetic_documents_the_gap() -> None:
    """The trust alert precedes the blanket sweep by the whole gap the fix closes."""
    assert _TRUST_ALERT_S == 7200
    assert _BLANKET_SWEEP_S == 9000
    assert _TIGHT_SWEEP_S == 8400
    # The tight sweep fires strictly earlier than the blanket sweep...
    assert _TIGHT_SWEEP_S < _BLANKET_SWEEP_S
    # ...yet still strictly after the worst-case legitimate cycle age, so it
    # can never restart a healthy in-flight cycle.
    assert _TIGHT_SWEEP_S > _LEGIT_FLOOR_S


@pytest.mark.asyncio
async def test_staging_bisect_remediated_inside_the_gap(tmp_path: Path) -> None:
    """The core regression: a hung staging_bisect is auto-restarted at 8500s.

    8500s is past the tight threshold (8400s) but *inside* the old blanket
    window (9000s) — precisely the ~30-min gap where #10234 had no remediation.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "staging_bisect")
    elapsed = 8500
    assert _TIGHT_SWEEP_S < elapsed < _BLANKET_SWEEP_S
    state.get_worker_heartbeats.return_value = {"staging_bisect": _hb(elapsed)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("staging_bisect")


@pytest.mark.asyncio
async def test_non_opt_in_loop_still_waits_for_the_blanket_window(
    tmp_path: Path,
) -> None:
    """A same-shaped loop NOT in worker_stall_tight_loops keeps the 9000s blanket.

    This is the gap the fix deliberately leaves untouched for everything except
    opted-in loops — confirming the tighter threshold is scoped, not global.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "workspace_gc")
    state.get_worker_heartbeats.return_value = {"workspace_gc": _hb(8500)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_legitimate_long_cycle_not_false_restarted(tmp_path: Path) -> None:
    """A healthy max-length bisect cycle (elapsed at the legit floor) is spared.

    7800s = interval + cycle_timeout is the longest a healthy cycle can leave
    the heartbeat stale (the watchdog cancels any cycle at cycle_timeout). It
    sits below the tight threshold, so the sweep does not restart it.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "staging_bisect")
    assert _LEGIT_FLOOR_S < _TIGHT_SWEEP_S
    state.get_worker_heartbeats.return_value = {
        "staging_bisect": _hb(_LEGIT_FLOOR_S)
    }
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()

"""Regression for #11091: staleness-alert-to-auto-remediation gap for
skill_prompt_eval.

``TrustFleetSanityLoop`` alerts on a stale ``skill_prompt_eval`` heartbeat at
its own staleness window — ``max(2 x interval, cycle_timeout)`` =
``max(1209600, 7200)`` = 1209600s (14d). But the only *automated remediation*
for a genuinely hung loop is ``HealthMonitorLoop``'s generic stall sweep,
whose blanket threshold is ``_WORKER_STALL_MULTIPLIER (3) x interval +
cycle_timeout`` = ``1814400 + 7200`` = 1821600s (~21.1d). That left a full
extra week (1209600s -> 1821600s) in which a trust-fleet anomaly issue exists
but the sweep has not even attempted a restart — the same class of gap #10241
closed for ``staging_bisect`` and #10795 closed for ``flake_tracker``, here
widened further by ``skill_prompt_eval``'s weekly (604800s) poll interval.

The fix opts ``skill_prompt_eval`` into the existing tight-sweep mechanism
(``worker_stall_tight_loops`` / ``worker_stall_tight_multiplier``, default 2),
dropping the threshold to ``2 x 604800 + 7200`` = 1216800s, firing the
auto-restart ~20 minutes after the trust alert instead of ~7 days later. The
multiplier floor (ge=1) keeps the threshold strictly above the worst-case
*legitimate* heartbeat age (one pre-cycle interval + a full ``cycle_timeout``
= 612000s), so a legitimately long in-flight cycle is still never
false-restarted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from health_monitor_loop import HealthMonitorLoop

# skill_prompt_eval shape: 604800s (7d) poll, 7200s (2h) per-cycle watchdog.
_INTERVAL_S = 604800
_CYCLE_TIMEOUT_S = 7200
# TrustFleetSanityLoop staleness alert (post-#10236): max(2 x interval, cycle).
_TRUST_ALERT_S = max(2 * _INTERVAL_S, _CYCLE_TIMEOUT_S)  # 1209600
# Blanket sweep threshold: 3 x interval + cycle_timeout.
_BLANKET_SWEEP_S = 3 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 1821600
# Tight sweep threshold (this fix): 2 x interval + cycle_timeout.
_TIGHT_SWEEP_S = 2 * _INTERVAL_S + _CYCLE_TIMEOUT_S  # 1216800
# Worst-case legitimate heartbeat age: one pre-cycle sleep + a full watchdog.
_LEGIT_FLOOR_S = _INTERVAL_S + _CYCLE_TIMEOUT_S  # 612000


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
        "hm_11091_test",
        tmp_path / "dedup" / "hm_11091_test.json",
    )
    return hm, state, bg_workers


def test_threshold_arithmetic_documents_the_gap() -> None:
    """The trust alert precedes the blanket sweep by the whole gap the fix closes."""
    assert _TRUST_ALERT_S == 1209600
    assert _BLANKET_SWEEP_S == 1821600
    assert _TIGHT_SWEEP_S == 1216800
    # The tight sweep fires strictly earlier than the blanket sweep...
    assert _TIGHT_SWEEP_S < _BLANKET_SWEEP_S
    # ...yet still strictly after the worst-case legitimate cycle age, so it
    # can never restart a healthy in-flight cycle.
    assert _TIGHT_SWEEP_S > _LEGIT_FLOOR_S


@pytest.mark.asyncio
async def test_skill_prompt_eval_remediated_inside_the_gap(tmp_path: Path) -> None:
    """The core regression: a hung skill_prompt_eval is auto-restarted well
    before the old blanket window, instead of waiting out an extra week.

    1300000s sits past the tight threshold (1216800s) but *inside* the old
    blanket window (1821600s) — precisely the gap where the trust-fleet alert
    (#11091's ``elapsed_s: 1209630`` breach) had already fired with nothing
    yet remediating.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "skill_prompt_eval")
    elapsed = 1_300_000
    assert _TIGHT_SWEEP_S < elapsed < _BLANKET_SWEEP_S
    state.get_worker_heartbeats.return_value = {"skill_prompt_eval": _hb(elapsed)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("skill_prompt_eval")


@pytest.mark.asyncio
async def test_legitimate_long_cycle_not_false_restarted(tmp_path: Path) -> None:
    """A healthy max-length skill_prompt_eval cycle (elapsed at the legit
    floor) is spared.

    612000s = interval + cycle_timeout is the longest a healthy cycle can
    leave the heartbeat stale (the watchdog cancels any cycle at
    cycle_timeout). It sits below the tight threshold, so the sweep does not
    restart it.
    """
    hm, state, bg_workers = _make_hm(tmp_path, "skill_prompt_eval")
    assert _LEGIT_FLOOR_S < _TIGHT_SWEEP_S
    state.get_worker_heartbeats.return_value = {
        "skill_prompt_eval": _hb(_LEGIT_FLOOR_S)
    }
    await hm._check_worker_staleness()
    bg_workers.restart.assert_not_awaited()

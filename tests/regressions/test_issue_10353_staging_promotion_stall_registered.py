"""Regression pins for #10353 piece (b) — StagingPromotionLoop loop-liveness.

Issue #10353 (G1) records that "no watchdog noticed the promotion loop itself
had stopped cutting RCs." The generic HealthMonitorLoop stall sweep
(`_check_worker_staleness`, #9650) restarts any *registered* loop whose
heartbeat goes silent — but only for loops in
`BGWorkerManager.registered_loop_names()` (the orchestrator `bg_loop_registry`
keys) and NOT in `_WORKER_STALL_EXCLUDED`.

These pins lock in that `staging_promotion` is covered by that sweep so a future
refactor can't silently drop the promotion loop out of supervision:

1. `staging_promotion` is registered in the orchestrator `bg_loop_registry`.
2. `staging_promotion` is NOT in the stall-sweep exclusion set.
3. Behaviourally, a silent (stale-heartbeat) `staging_promotion` loop is
   restarted by the sweep.

The "work-picker" (`IssueStore` / the `store` pipeline phase) is deliberately
NOT a registered `BaseBackgroundLoop` — pipeline phases have different
supervision semantics (no interval/watchdog contract) and are intentionally out
of this generic loop sweep; bringing them under supervision is a separate design
(tracked on the epic #10351 G4/G5), not this pin.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from config import HydraFlowConfig
from health_monitor_loop import _WORKER_STALL_EXCLUDED, HealthMonitorLoop

_ORCHESTRATOR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator.py"
)


def test_staging_promotion_registered_in_bg_loop_registry() -> None:
    """The orchestrator must register the promotion loop so the stall sweep
    (which iterates ``registered_loop_names()``) can see it."""
    source = _ORCHESTRATOR.read_text(encoding="utf-8")
    assert '"staging_promotion": svc.staging_promotion_loop' in source, (
        "staging_promotion dropped from orchestrator bg_loop_registry — the "
        "worker-stall sweep would no longer supervise the promotion loop (#10353)"
    )


def test_staging_promotion_not_excluded_from_stall_sweep() -> None:
    """`staging_promotion` must NOT be in the stall-sweep exclusion set, else a
    silent promotion loop would never be restarted/escalated."""
    assert "staging_promotion" not in _WORKER_STALL_EXCLUDED


@pytest.fixture
def hm_env(tmp_path: Path):
    from dedup_store import DedupStore

    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.registered_loop_names.return_value = {"staging_promotion"}
    bg_workers.get_interval.return_value = 300
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
        "hm_worker_stall_10353_test",
        tmp_path / "dedup" / "hm_worker_stall_10353_test.json",
    )
    return hm, state, bg_workers, prs


def _stale_hb(age_seconds: int) -> dict:
    stamp = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return {"status": "ok", "last_run": stamp, "details": {}}


@pytest.mark.asyncio
async def test_silent_staging_promotion_loop_is_restarted(hm_env) -> None:
    """A stalled (silent-heartbeat) promotion loop is caught by the sweep."""
    hm, state, bg_workers, _prs = hm_env
    # threshold = 3 * 300 + 100 = 1000s; 3000s is well past it.
    state.get_worker_heartbeats.return_value = {"staging_promotion": _stale_hb(3000)}
    await hm._check_worker_staleness()
    bg_workers.restart.assert_awaited_once_with("staging_promotion")

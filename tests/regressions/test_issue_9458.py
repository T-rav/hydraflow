"""Regression for issue #9458 — false-positive repair_ratio HITL escalation.

HITL #9458 was auto-filed by `TrustFleetSanityLoop`'s `repair_ratio` detector
against the `pr_unsticker` loop with `failed=1, repaired=0, status=no_successes`.
It was a false positive for three independent reasons, any one of which would
have suppressed it:

(A) Minimum-sample: a single failure (`failed_day=1`) with zero recorded
    successes is not enough signal to escalate. `detect_repair_ratio` now
    requires `failed_day >= loop_anomaly_repair_min_sample` (default 3) before
    the `no_successes` branch breaches; below the floor it returns no breach
    with `status="insufficient_data"`, mirroring the zero/zero guard.

(B) Repaired semantics: the collector only ever read a literal `repaired`
    details key, which NO production loop emits — so `repaired_day` was
    permanently 0 for every loop and the detector could only ever see
    `no_successes`. The collector now credits each trust loop's real
    success-outcome key (`resolved`, `refreshed`, `updated`, `merged`,
    `reverted`, `cases_filed`, ...) toward `repaired_day`.

(C) Trust-loop scoping: `repair_ratio`, `tick_error_ratio`, and `cost_spike`
    now only run for workers in :data:`TRUST_LOOP_WORKERS`, exactly the way
    staleness is already gated. `pr_unsticker` and `dependabot_merge` are
    registered *non-trust* background workers that emit `failed` with no
    `repaired`; they must be excluded or they produce identical false-positive
    HITLs on any routine CI / bot-PR failure.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from trust_fleet_anomaly_detectors import TRUST_LOOP_WORKERS, detect_repair_ratio
from trust_fleet_sanity_loop import TrustFleetSanityLoop


def test_single_failure_below_min_sample_does_not_breach() -> None:
    metrics = {"repaired_day": 0, "failed_day": 1}
    breached, details = detect_repair_ratio(
        "pr_unsticker",
        metrics,
        threshold=2.0,
        min_sample=3,
    )
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_min_sample_floor_is_inclusive_lower_bound() -> None:
    below = detect_repair_ratio(
        "x", {"repaired_day": 0, "failed_day": 2}, threshold=2.0, min_sample=3
    )
    assert below[0] is False
    assert below[1]["status"] == "insufficient_data"

    at_floor = detect_repair_ratio(
        "x", {"repaired_day": 0, "failed_day": 3}, threshold=2.0, min_sample=3
    )
    assert at_floor[0] is True
    assert at_floor[1]["status"] == "no_successes"


def test_default_config_carries_min_sample_floor() -> None:
    cfg = HydraFlowConfig(data_root=Path("/tmp"), repo="hydra/hydraflow")
    assert cfg.loop_anomaly_repair_min_sample == 3


def _make_loop(tmp_path: Path, *, bus: EventBus) -> TrustFleetSanityLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        trust_fleet_sanity_interval=600,
    )
    loop = TrustFleetSanityLoop.__new__(TrustFleetSanityLoop)
    loop._config = cfg
    loop._source_bus = bus
    return loop


def _status_event(
    worker: str, details: dict[str, object], *, ago_s: int = 900
) -> HydraFlowEvent:
    ts = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=ago_s)).isoformat()
    return HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=ts,
        data={"worker": worker, "status": "ok", "details": details},
    )


@pytest.mark.asyncio
async def test_success_outcome_credits_repaired_day(tmp_path: Path) -> None:
    events = [_status_event("flake_tracker", {"filed": 1, "resolved": 4, "failed": 1})]

    async def _load(since: _dt.datetime) -> list[HydraFlowEvent]:
        return [e for e in events if e.timestamp >= since.isoformat()]

    bus = EventBus()
    bus.load_events_since = _load  # type: ignore[method-assign]
    loop = _make_loop(tmp_path, bus=bus)

    metrics = await loop._collect_window_metrics()
    assert metrics["flake_tracker"]["repaired_day"] == 4
    assert metrics["flake_tracker"]["failed_day"] == 1


def _make_breach_world(tmp_path: Path, worker: str):
    from tests.scenarios.fakes.mock_world import MockWorld
    from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

    world = MockWorld(tmp_path)
    now = _dt.datetime.now(_dt.UTC)
    seeded_bus = EventBus()
    event = HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=(now - _dt.timedelta(seconds=900)).isoformat(),
        data={
            "worker": worker,
            "status": "ok",
            "details": {"filed": 0, "repaired": 0, "failed": 5},
        },
    )

    async def _load(since: _dt.datetime) -> list[HydraFlowEvent]:
        return [event] if event.timestamp >= since.isoformat() else []

    seeded_bus.load_events_since = _load  # type: ignore[method-assign]

    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    state.get_trust_fleet_sanity_attempts.return_value = 0
    state.inc_trust_fleet_sanity_attempts.return_value = 1
    state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

    _seed_ports(world, trust_fleet_sanity_state=state, event_bus=seeded_bus)
    return world


@pytest.mark.scenario_loops
@pytest.mark.asyncio
@pytest.mark.parametrize("worker", ["pr_unsticker", "dependabot_merge"])
async def test_non_trust_worker_excluded_from_repair_ratio(
    tmp_path: Path, worker: str
) -> None:
    assert worker not in TRUST_LOOP_WORKERS
    world = _make_breach_world(tmp_path, worker)

    stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

    assert stats["trust_fleet_sanity"]["status"] == "ok", stats
    assert stats["trust_fleet_sanity"].get("filed", 0) == 0, stats
    assert world.github._issues == {}

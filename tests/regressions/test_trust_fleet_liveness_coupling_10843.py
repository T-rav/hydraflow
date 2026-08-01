"""Regression (#10843): trust_fleet_sanity_interval is HealthMonitorLoop's fast
stall-sweep cadence — damper-0a must not slow it past the heavy-pass tick.

Damper-0a (#10843) raised several genuinely-slow loop cadences to their
measurement window. ``trust_fleet_sanity_interval`` *looks* like one of them
(fleet anomaly over time) but ``HealthMonitorLoop._get_default_interval()``
borrows it as the cadence of its restart-first stall sweep, and the stall
threshold is ``_SANITY_STALL_MULTIPLIER × trust_fleet_sanity_interval``
(``health_monitor_loop.py``). An in-progress damper-0a change raised the field's
default 600→3600 AND lifted its ``le`` ceiling to a week — which would let an
operator push the "fast" stall sweep *slower* than HealthMonitor's own heavy
caretaker pass (``health_monitor_interval``, 7200s), silently regressing liveness
detection. This pins the invariant so the field can't be re-slowed past the
heavy pass by default or by its bound.
"""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_trust_fleet_sanity_default_keeps_stall_sweep_faster_than_heavy_pass() -> None:
    cfg = HydraFlowConfig()
    # The fast stall sweep runs at trust_fleet_sanity_interval; the ~9 heavy
    # caretaker checks run at health_monitor_interval. The sweep must stay
    # strictly faster, or a stall alert cannot be re-evaluated before the heavy
    # body — the property damper-0a must not regress.
    assert cfg.trust_fleet_sanity_interval < cfg.health_monitor_interval


def test_trust_fleet_sanity_ceiling_cannot_exceed_the_heavy_pass() -> None:
    # Even at its MAX allowed value the fast sweep must stay below the heavy
    # pass. The le ceiling (3600) enforces this; lifting it to a week — as the
    # first damper-0a draft did — would make this construction succeed and
    # invert HealthMonitor's fast/heavy relationship.
    heavy_pass = HydraFlowConfig().health_monitor_interval
    with pytest.raises(ValueError, match="less than or equal to"):
        HydraFlowConfig(trust_fleet_sanity_interval=heavy_pass + 1)

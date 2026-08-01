"""Ratchet: slow-signal loops must not over-sample their measurement window (#10843).

Damper 0a (the cheapest damper in the stillness program, #10819): a loop that
evaluates a monthly signal every 4 min has ~180× the opportunities to fire on the
same underlying data, so its finding rate is driven by polling frequency, not by
the condition it detects (mechanism-1 signal-to-noise collapse). The fix was one
config value per loop; this ratchet pins the aligned defaults so the mismatch
cannot silently return when a loop is added or an interval is re-tuned.

The floor for each loop is the aligned tick (≤ the measurement window its output
describes); the comment records that window. escape_ledger and sampled_audit are
deliberately NOT ratcheted here — they carry escape-*detection* / gauntlet-
*sampling* coverage roles beyond trend measurement, so their cadence is a separate
per-loop call for the operator (see #10843's "confirm per loop").
"""

from __future__ import annotations

from config import HydraFlowConfig

#: loop interval field → aligned floor (tick must be at least this; measurement
#: window in the comment). Damper 0a raised each from a sub-window cadence.
#: NOT ratcheted: ``trust_fleet_sanity_interval``. It reads as a slow signal
#: (fleet anomaly over time) but ``HealthMonitorLoop._get_default_interval``
#: *borrows* it as the cadence of its fast restart-first stall sweep, and the
#: stall threshold is ``_SANITY_STALL_MULTIPLIER × trust_fleet_sanity_interval``
#: — so slowing it to an hourly tick would regress liveness detection 6× and
#: (raising its ``le`` past 3600) break HealthMonitor's documented "fast sweep
#: < heavy pass" invariant. The field is dual-purpose; decoupling it (a
#: dedicated fast-sweep field) is a stillness ruling, not a cadence alignment.
_ALIGNED_FLOORS = {
    "retrospective_interval": 86400,  # long-horizon: did a past proposal help → daily
    "detector_calibration_interval": 86400,  # a detector escalating one subject → daily
    "second_order_vitals_interval": 86400,  # residual monitor, monthly signal → daily
    "intervention_tally_interval": 86400,  # interventions / 100 merges (monthly) → daily
    "erosion_metrics_interval": 86400,  # per-change erosion + monthly trend → daily
}


def test_slow_signal_loops_do_not_oversample() -> None:
    cfg = HydraFlowConfig()
    too_fast = {
        field: getattr(cfg, field)
        for field, floor in _ALIGNED_FLOORS.items()
        if getattr(cfg, field) < floor
    }
    assert not too_fast, (
        "These loops measure a slow signal but their default tick is faster than "
        "the aligned floor — over-sampling inflates finding count without adding "
        f"information (damper 0a, #10843). Raise the interval: {too_fast}"
    )

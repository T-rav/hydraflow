"""Regression for issue #9811 — false-positive tick_error_ratio HITL escalation.

HITL #9811 was auto-filed by `TrustFleetSanityLoop`'s `tick_error_ratio`
detector against the `fake_coverage_auditor` loop with `ticks_total=2,
ticks_errored=1, ratio=0.5` against `threshold=0.2`. It was a false positive:
`fake_coverage_auditor` is a weekly-cadence loop with 0-2 ticks/24h, so a
single transient tick error produces a high *ratio* off a sample too small to
mean anything.

`detect_tick_error_ratio` now requires `ticks_total >=
loop_anomaly_tick_error_min_sample` (default 3) before it can breach; below
the floor it returns no breach with `status="insufficient_data"`, mirroring
the `detect_repair_ratio` min-sample guard added for issue #9458.
"""

from __future__ import annotations

from pathlib import Path

from config import HydraFlowConfig
from trust_fleet_anomaly_detectors import detect_tick_error_ratio


def test_issue_repro_below_min_sample_does_not_breach() -> None:
    """Exact repro from #9811: ticks_total=2, ticks_errored=1, threshold=0.2."""
    metrics = {"ticks_total": 2, "ticks_errored": 1}
    breached, details = detect_tick_error_ratio(
        "fake_coverage_auditor",
        metrics,
        threshold=0.2,
        min_sample=3,
    )
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_min_sample_floor_is_inclusive_lower_bound() -> None:
    below = detect_tick_error_ratio(
        "x", {"ticks_total": 2, "ticks_errored": 1}, threshold=0.2, min_sample=3
    )
    assert below[0] is False
    assert below[1]["status"] == "insufficient_data"

    at_floor = detect_tick_error_ratio(
        "x", {"ticks_total": 3, "ticks_errored": 1}, threshold=0.2, min_sample=3
    )
    assert at_floor[0] is True
    assert "ratio" in at_floor[1]


def test_real_anomaly_at_or_above_floor_still_breaches() -> None:
    """A genuine anomaly with enough samples must still escalate."""
    breached, details = detect_tick_error_ratio(
        "x",
        {"ticks_total": 10, "ticks_errored": 5},
        threshold=0.2,
        min_sample=3,
    )
    assert breached is True
    assert details["ratio"] == 0.5


def test_default_min_sample_is_one_when_unspecified() -> None:
    """Callers that don't pass min_sample keep today's behavior (no regression)."""
    breached, details = detect_tick_error_ratio(
        "x", {"ticks_total": 2, "ticks_errored": 1}, threshold=0.2
    )
    assert breached is True
    assert details["ratio"] == 0.5


def test_default_config_carries_min_sample_floor() -> None:
    cfg = HydraFlowConfig(data_root=Path("/tmp"), repo="hydra/hydraflow")
    assert cfg.loop_anomaly_tick_error_min_sample == 3

"""Unit tests for the second-order vitals verdict engine (#10373).

Covers the decided divergence logic: k-of-5 families with the sustained-window
requirement, the green / watch / diverging boundaries, the primary-health
precondition, honest partial-coverage degradation, and that single-window
spikes and single-series noise never fire.
"""

from __future__ import annotations

from vitals.models import (
    FAMILY_AUDIT,
    FAMILY_ESCAPES,
    FAMILY_INTERVENTION,
    SERIES_AUDIT_DISAGREEMENT,
    SERIES_EROSION_DUPLICATION,
    SERIES_EROSION_SCATTER,
    SERIES_EROSION_SPREAD,
    SERIES_ESCAPES,
    SERIES_FAIL_OPEN,
    SERIES_INDEPENDENCE_UNAVAILABLE,
    SERIES_INTERVENTION_CORRECTIONS,
    VitalsThresholds,
)
from vitals.verdict import (
    VERDICT_DIVERGING,
    VERDICT_GREEN,
    VERDICT_WATCH,
    evaluate_vitals,
)

# min_baseline_windows=3, sustained_windows=2 → a series needs ≥5 points to
# breach and ≥3 to report.
_THRESHOLDS = VitalsThresholds(
    min_baseline_windows=3, sustained_windows=2, watch_k=2, diverging_k=3
)

# A frozen [0,0,0] baseline then two sustained high windows → sustained breach.
_BREACHING = [0.0, 0.0, 0.0, 10.0, 10.0]
# Same length, reporting, but flat → never breaches.
_FLAT = [0.0, 0.0, 0.0, 0.0, 0.0]
# Only the newest window is high (a one-window blip) → never breaches.
_SPIKE = [0.0, 0.0, 0.0, 0.0, 10.0]
# Too few points to carry a baseline → not reporting.
_YOUNG = [0.0, 0.0]

_ALL_SINGLE = (
    SERIES_ESCAPES,
    SERIES_EROSION_SPREAD,
    SERIES_EROSION_SCATTER,
    SERIES_EROSION_DUPLICATION,
    SERIES_INTERVENTION_CORRECTIONS,
    SERIES_AUDIT_DISAGREEMENT,
    SERIES_FAIL_OPEN,
    SERIES_INDEPENDENCE_UNAVAILABLE,
)


def _all_flat() -> dict[str, list[float]]:
    return {name: list(_FLAT) for name in _ALL_SINGLE}


class TestVerdictBoundaries:
    def test_three_families_sustained_is_diverging(self) -> None:
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
        h[SERIES_AUDIT_DISAGREEMENT] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.verdict == VERDICT_DIVERGING
        assert v.k == 3
        assert set(v.breaching_families) == {
            FAMILY_ESCAPES,
            FAMILY_INTERVENTION,
            FAMILY_AUDIT,
        }
        assert v.reporting_families == 5

    def test_two_families_sustained_is_watch(self) -> None:
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.verdict == VERDICT_WATCH
        assert v.k == 2

    def test_one_family_is_green(self) -> None:
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.verdict == VERDICT_GREEN
        assert v.k == 1


class TestPrimaryHealthPrecondition:
    def test_diverging_suppressed_when_primary_not_green(self) -> None:
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
        h[SERIES_AUDIT_DISAGREEMENT] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=False, thresholds=_THRESHOLDS)
        # k is still computed (the families ARE drifting) but the verdict is
        # green: divergence-while-green is the whole signal.
        assert v.k == 3
        assert v.verdict == VERDICT_GREEN
        assert v.primary_health_green is False


class TestFamilyRollup:
    def test_erosion_family_breaches_on_any_subseries(self) -> None:
        # Only one of erosion's three sub-series drifts → the family still counts
        # as ONE breaching family (never three votes from one family).
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
        h[SERIES_EROSION_SCATTER] = list(_BREACHING)  # erosion via one sub-series
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.k == 3
        assert v.verdict == VERDICT_DIVERGING

    def test_independence_family_breaches_on_fail_open_alone(self) -> None:
        h = _all_flat()
        h[SERIES_ESCAPES] = list(_BREACHING)
        h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
        h[SERIES_FAIL_OPEN] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.k == 3
        assert v.verdict == VERDICT_DIVERGING


class TestAntiFlap:
    def test_single_window_spike_never_fires(self) -> None:
        h = {name: list(_SPIKE) for name in _ALL_SINGLE}
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.k == 0
        assert v.verdict == VERDICT_GREEN


class TestHonestDegradation:
    def test_partial_coverage_reports_n_of_5(self) -> None:
        # Only the escapes family is reporting; the rest are too young.
        h = {name: list(_YOUNG) for name in _ALL_SINGLE}
        h[SERIES_ESCAPES] = list(_BREACHING)
        v = evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.reporting_families == 1
        assert v.total_families == 5
        assert v.coverage_label == "1-of-5 reporting"
        # One breaching family is below the watch bar → green, honestly partial.
        assert v.verdict == VERDICT_GREEN

    def test_absent_series_are_not_a_green_vote(self) -> None:
        # No histories at all → nothing reporting, verdict green (0-of-5).
        v = evaluate_vitals({}, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v.reporting_families == 0
        assert v.verdict == VERDICT_GREEN
        assert v.coverage_label == "0-of-5 reporting"

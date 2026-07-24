"""Unit tests for the second-order vitals verdict engine (#10373).

Covers the decided divergence logic: k-of-5 families with the sustained-window
requirement, the green / watch / diverging boundaries, the primary-health
precondition, honest partial-coverage degradation, and that single-window
spikes and single-series noise never fire.
"""

from __future__ import annotations

from vitals.control import individuals_limits
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
    _series_sustained_breach,
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

# A genuinely NON-FLAT baseline: mean (centre) = 11.0, MR̄ = 2.0 → σ̂ = 2/1.128,
# so the 3σ UCL ≈ 16.32. A value of 14 sits ABOVE the mean but INSIDE the band
# (must not breach); 30 sits above the UCL (must breach). This is the fixture the
# all-zero baselines elsewhere cannot express — with σ̂=0 the band collapses and a
# breach degenerates to ``value > 0``.
_NONFLAT_BASE = [10.0, 12.0, 10.0, 12.0, 10.0, 12.0]
_WITHIN_BAND = 14.0
_ABOVE_UCL = 30.0
_THREE_FAMILY_SERIES = (
    SERIES_ESCAPES,
    SERIES_INTERVENTION_CORRECTIONS,
    SERIES_AUDIT_DISAGREEMENT,
)


def _nonflat(recent: float) -> list[float]:
    """The non-flat baseline followed by two sustained windows at ``recent``."""
    return [*_NONFLAT_BASE, recent, recent]


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


class TestThreeSigmaBandIsLoadBearing:
    """The 3σ band must be REAL, not decorative.

    Every other fixture here uses an all-zero baseline, where σ̂ = 0 collapses
    centre == UCL == 0 and "breach" degenerates to ``value > 0`` — the whole
    ``centre + 3σ̂`` band could be deleted (compare to the mean instead of the
    UCL) undetected. These tests use a NON-flat baseline where the mean and the
    UCL genuinely differ, so a value above the mean but inside the band must NOT
    breach and only a value above the UCL does. They FAIL if the band is removed.
    """

    def test_baseline_band_has_real_width(self) -> None:
        centre, ucl = individuals_limits(_NONFLAT_BASE)
        assert centre == 11.0
        assert ucl > 16.0  # ≈ 16.32; comfortably wider than the mean
        # The chosen probe values straddle the band: 14 inside, 30 above.
        assert centre < _WITHIN_BAND < ucl
        assert ucl < _ABOVE_UCL

    def test_value_within_band_does_not_sustained_breach(self) -> None:
        # recent = [14, 14]: above the mean (11) but below the UCL (≈16.32).
        assert not _series_sustained_breach(
            _nonflat(_WITHIN_BAND), min_baseline_windows=3, sustained_windows=2
        )

    def test_value_above_ucl_sustained_breaches(self) -> None:
        # recent = [30, 30]: above the UCL → a genuine sustained breach.
        assert _series_sustained_breach(
            _nonflat(_ABOVE_UCL), min_baseline_windows=3, sustained_windows=2
        )

    def test_one_window_above_one_within_is_not_sustained(self) -> None:
        # recent = [30 (above UCL), 14 (within band)] → not ALL above → no breach.
        h = [*_NONFLAT_BASE, _ABOVE_UCL, _WITHIN_BAND]
        assert not _series_sustained_breach(
            h, min_baseline_windows=3, sustained_windows=2
        )

    def test_evaluate_within_band_is_green_above_ucl_is_diverging(self) -> None:
        # Three families with a non-flat baseline. Within-band recent windows →
        # k=0 green; above-UCL recent windows → k=3 diverging. If the band were
        # removed, the within-band case (14 > mean 11) would read as diverging.
        within = _all_flat()
        for name in _THREE_FAMILY_SERIES:
            within[name] = _nonflat(_WITHIN_BAND)
        v_within = evaluate_vitals(
            within, primary_health_green=True, thresholds=_THRESHOLDS
        )
        assert v_within.k == 0
        assert v_within.verdict == VERDICT_GREEN

        above = _all_flat()
        for name in _THREE_FAMILY_SERIES:
            above[name] = _nonflat(_ABOVE_UCL)
        v_above = evaluate_vitals(
            above, primary_health_green=True, thresholds=_THRESHOLDS
        )
        assert v_above.k == 3
        assert v_above.verdict == VERDICT_DIVERGING


class TestReportingRequiresPrimedFrozenBaseline:
    """A family reports only once its FROZEN baseline (not raw window count) is
    primed — the points the control limit is actually computed from. Gating on
    raw windows overstated readiness by ``sustained_windows``.
    """

    def test_reporting_counts_frozen_baseline_not_raw_windows(self) -> None:
        # min_baseline_windows=3, sustained_windows=2. A 4-point history has a
        # frozen baseline of only 2 points (< 3): its limit is noise, so the
        # family must NOT be reporting even though raw windows (4) ≥ 3.
        four = {SERIES_ESCAPES: [0.0, 0.0, 0.0, 5.0]}
        v4 = evaluate_vitals(four, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v4.reporting_families == 0
        # One more point → the frozen baseline is 3 points → now reporting.
        five = {SERIES_ESCAPES: [0.0, 0.0, 0.0, 0.0, 5.0]}
        v5 = evaluate_vitals(five, primary_health_green=True, thresholds=_THRESHOLDS)
        assert v5.reporting_families == 1

"""Unit tests for the vitals methodology engine (#10838, ADR-0133).

The spec is the ticket's *published numbers*: the group-chart widening anchors
(Mortell & Runger: 10 streams → 3.64σ), the ~3.4σ-at-70-charts headline, the MDE
table, and the g/t-chart formulas. Each assertion pins one of those so a drift in
the arithmetic is caught, not silently absorbed.
"""

from __future__ import annotations

import math
from dataclasses import replace
from statistics import NormalDist

import pytest

from vitals_methodology import (
    CLASSIC_SHEWHART_SIGMA,
    TRIAGE_BUDGET_PER_CYCLE,
    AlarmDefinition,
    AlarmPriority,
    MultiplicityMethod,
    TBEChartLimits,
    can_chart,
    consecutive_zeros_run_limit,
    mde_baseline_events,
    rationalize,
    time_between_events_limits,
    widened_sigma_multiplier,
)


class TestWidenedSigmaMultiplier:
    def test_single_instrument_floors_at_classic_three_sigma(self) -> None:
        # One chart under a 5% budget would compute 1.96σ (looser than classic),
        # but we only ever widen — the floor keeps a small fleet at classic 3σ.
        assert widened_sigma_multiplier(1) == CLASSIC_SHEWHART_SIGMA

    def test_seventy_charts_at_five_percent_is_about_3_4_sigma(self) -> None:
        # The ticket's headline: "70 charts at 5% monthly gives α ≈ 0.0007,
        # i.e. ~3.4-sigma rather than 3-sigma."
        assert widened_sigma_multiplier(70) == pytest.approx(3.4, abs=0.05)

    def test_group_chart_anchor_ten_streams_moves_L_to_3_64(self) -> None:
        # Mortell & Runger 1995 / Epprecht 2011: keeping the whole fleet's
        # UPPER-tail false-alarm rate equal to a single one-sided 3σ chart
        # across 10 streams moves L from 3.00 to 3.64. The family budget is the
        # one-sided 3σ tail Φ(−3) ≈ 0.00135.
        single_chart_3sigma_tail = NormalDist(0.0, 1.0).cdf(-3.0)  # ≈ 0.00135
        assert widened_sigma_multiplier(
            10,
            family_wise_monthly=single_chart_3sigma_tail,
            two_sided=False,
            method=MultiplicityMethod.SIDAK,
        ) == pytest.approx(3.64, abs=0.03)

    def test_more_instruments_widen_the_limit_monotonically(self) -> None:
        widths = [widened_sigma_multiplier(n) for n in (1, 10, 70, 300)]
        assert widths == sorted(widths)

    def test_multiplier_is_the_exact_bonferroni_probit_of_chart_count(self) -> None:
        # The cycle-granularity ruling means L is a pure function of the
        # registered chart count — this function has no tick/cadence input at all
        # (that invariant is enforced at the call site, which evaluates once per
        # cycle). Pin the EXACT two-sided Bonferroni probit for n=70 against an
        # independently computed value, so a regression in the formula, the
        # default method, or the floor is caught — not merely that a pure
        # function returns the same thing twice.
        expected = NormalDist(0.0, 1.0).inv_cdf(1.0 - (0.05 / 70) / 2.0)
        assert widened_sigma_multiplier(70) == pytest.approx(expected, abs=1e-9)

    def test_nonpositive_count_degrades_to_classic_three_sigma(self) -> None:
        assert widened_sigma_multiplier(0) == CLASSIC_SHEWHART_SIGMA
        assert widened_sigma_multiplier(-5) == CLASSIC_SHEWHART_SIGMA

    def test_sidak_is_marginally_tighter_than_bonferroni(self) -> None:
        bonf = widened_sigma_multiplier(70, method=MultiplicityMethod.BONFERRONI)
        sidak = widened_sigma_multiplier(70, method=MultiplicityMethod.SIDAK)
        assert sidak < bonf
        assert bonf - sidak < 0.01  # they agree to two decimals at this scale


class TestMinimumDetectableEffect:
    @pytest.mark.parametrize(
        ("rate_ratio", "expected_events"),
        [
            (2.0, 11),
            (1.5, 39),
            (1.25, 141),
            (1.1, 824),
            (0.5, 23),
            (0.75, 109),
            (0.9, 745),
        ],
    )
    def test_reproduces_published_mde_table(
        self, rate_ratio: float, expected_events: int
    ) -> None:
        # The ticket's table (α=0.05 two-sided, 80% power). Round-up to an event
        # count; allow ±1 for the geometric rounding the table itself used.
        got = math.ceil(mde_baseline_events(rate_ratio))
        assert abs(got - expected_events) <= 1

    def test_no_effect_needs_infinite_data(self) -> None:
        assert mde_baseline_events(1.0) == math.inf

    def test_smaller_effects_need_more_baseline(self) -> None:
        # Detecting a 10% change needs far more events than detecting a doubling.
        assert mde_baseline_events(1.1) > mde_baseline_events(2.0)

    def test_nonpositive_rate_ratio_rejected(self) -> None:
        with pytest.raises(ValueError):
            mde_baseline_events(0.0)

    def test_can_chart_gates_on_power(self) -> None:
        # 1.5 events/month cannot detect a doubling (needs ~11); 20 can.
        assert not can_chart(1.5, 2.0)
        assert can_chart(20.0, 2.0)


class TestTimeBetweenEventsChart:
    def test_limits_follow_benneyan_formulas(self) -> None:
        # Independent numeric anchors for mean=30 (Benneyan 2001 g/t-chart):
        #   centre = 0.693·30           = 20.79
        #   UCL    = 30 + 3·√(30²+30)   = 30 + 3·√930 = 121.487704…
        #   LCL    = max(0, 30 − 91.49) = 0
        # Hardcoded literals, NOT a re-derivation of the implementation's formula.
        limits = time_between_events_limits(30.0)
        assert isinstance(limits, TBEChartLimits)
        assert limits.centre == pytest.approx(20.79, abs=1e-9)
        assert limits.upper == pytest.approx(121.487704, abs=1e-4)
        assert limits.lower == 0.0

    def test_lower_limit_is_pinned_at_zero(self) -> None:
        # For any positive mean the 3σ spread exceeds the mean, so LCL floors at 0
        # — which is exactly why the consecutive-zeros run rule is needed.
        assert time_between_events_limits(5.0).lower == 0.0

    def test_empty_mean_has_no_chart(self) -> None:
        limits = time_between_events_limits(0.0)
        assert limits == TBEChartLimits(centre=0.0, upper=0.0, lower=0.0)

    def test_consecutive_zeros_run_limit_grows_with_rarity(self) -> None:
        # A rarer process (larger mean interval) makes a single zero more
        # surprising, so fewer consecutive zeros are needed to alarm.
        rare = consecutive_zeros_run_limit(100.0)
        common = consecutive_zeros_run_limit(2.0)
        assert rare <= common
        assert rare >= 1

    def test_consecutive_zeros_run_limit_is_improbable_in_control(self) -> None:
        mean = 9.0  # p_zero = 1/10
        k = consecutive_zeros_run_limit(mean, alpha=0.05)
        p_zero = 1.0 / (mean + 1.0)
        assert p_zero**k <= 0.05
        assert p_zero ** (k - 1) > 0.05  # k is the SMALLEST such run


class TestAlarmRationalization:
    def _alarm(self, **over: object) -> AlarmDefinition:
        base = AlarmDefinition(
            instrument_id="finder_calibration",
            documented_response="widen the noise floor and re-baseline",
            priority=AlarmPriority.HIGH,
            consequence_of_inaction="finder alarms drift into permanent adverse",
        )
        return replace(base, **over)

    def test_fully_specified_alarm_is_rationalized(self) -> None:
        assert self._alarm().is_rationalized

    def test_alarm_without_response_is_not_an_alarm(self) -> None:
        assert not self._alarm(documented_response="   ").is_rationalized

    def test_alarm_without_consequence_is_not_an_alarm(self) -> None:
        assert not self._alarm(consequence_of_inaction="").is_rationalized

    def test_rationalize_partitions_keep_from_remove(self) -> None:
        good = self._alarm()
        bad = self._alarm(instrument_id="ghost", documented_response="")
        report = rationalize([good, bad])
        assert report.rationalized == (good,)
        assert report.to_remove == (bad,)

    def test_priority_counts_are_over_the_kept_set_only(self) -> None:
        report = rationalize(
            [
                self._alarm(priority=AlarmPriority.HIGH),
                self._alarm(priority=AlarmPriority.LOW),
                self._alarm(priority=AlarmPriority.LOW),
                self._alarm(consequence_of_inaction=""),  # dropped
            ]
        )
        assert report.priority_counts[AlarmPriority.HIGH] == 1
        assert report.priority_counts[AlarmPriority.LOW] == 2
        assert report.priority_counts[AlarmPriority.MEDIUM] == 0

    def test_over_triage_budget_flags_when_fleet_exceeds_cycle_capacity(self) -> None:
        under = rationalize([self._alarm() for _ in range(TRIAGE_BUDGET_PER_CYCLE)])
        over = rationalize([self._alarm() for _ in range(TRIAGE_BUDGET_PER_CYCLE + 1)])
        assert not under.over_triage_budget
        assert over.over_triage_budget

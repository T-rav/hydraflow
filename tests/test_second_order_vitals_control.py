"""Unit tests for the Shewhart individuals control chart (#10373).

Covers the per-series control limits the divergence verdict is built on:
mean moving range, the 3σ upper control limit (σ̂ = MR̄ / 1.128), and the
``min_windows`` gate that keeps a limit computed from too few points from ever
firing.
"""

from __future__ import annotations

import math

from vitals.control import (
    breaches_upper,
    individuals_limits,
    mean_moving_range,
)


class TestMeanMovingRange:
    def test_needs_two_points(self) -> None:
        assert mean_moving_range([]) == 0.0
        assert mean_moving_range([5.0]) == 0.0

    def test_flat_series_is_zero(self) -> None:
        assert mean_moving_range([3.0, 3.0, 3.0, 3.0]) == 0.0

    def test_alternating_series(self) -> None:
        # |12-10| = 2 each step → mean 2.0
        assert mean_moving_range([10.0, 12.0, 10.0, 12.0]) == 2.0


class TestIndividualsLimits:
    def test_empty_baseline(self) -> None:
        assert individuals_limits([]) == (0.0, 0.0)

    def test_single_point_has_no_dispersion(self) -> None:
        centre, ucl = individuals_limits([7.0])
        assert centre == 7.0
        assert ucl == 7.0  # MR undefined → σ̂ = 0

    def test_flat_baseline_ucl_equals_centre(self) -> None:
        centre, ucl = individuals_limits([2.0, 2.0, 2.0, 2.0])
        assert centre == 2.0
        assert ucl == 2.0

    def test_three_sigma_upper_limit(self) -> None:
        baseline = [10.0, 12.0, 10.0, 12.0]  # centre 11, MR̄ 2
        centre, ucl = individuals_limits(baseline)
        assert centre == 11.0
        expected = 11.0 + 3.0 * (2.0 / 1.128)
        assert math.isclose(ucl, expected, rel_tol=1e-9)


class TestBreachesUpper:
    def test_below_min_windows_never_breaches(self) -> None:
        # Even a wildly high value cannot breach until the baseline is primed.
        assert breaches_upper(999.0, [0.0, 0.0], min_windows=8) is False

    def test_flat_baseline_any_rise_breaches(self) -> None:
        baseline = [1.0] * 8
        assert breaches_upper(2.0, baseline, min_windows=8) is True
        # Exactly at the centre/UCL is not a breach (strictly greater).
        assert breaches_upper(1.0, baseline, min_windows=8) is False

    def test_value_within_control_limit_is_not_a_breach(self) -> None:
        baseline = [10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0]  # UCL ≈ 16.32
        assert breaches_upper(16.0, baseline, min_windows=8) is False
        assert breaches_upper(17.0, baseline, min_windows=8) is True

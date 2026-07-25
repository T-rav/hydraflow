from __future__ import annotations

import math
import statistics

import pytest
from hypothesis import given
from hypothesis import strategies as st

from signal_control.conditioners import Ewma


def test_ewma_seeds_to_first_value():
    e = Ewma(alpha=0.3)
    assert e.value is None
    assert e.update(10.0) == 10.0
    assert e.value == 10.0


def test_ewma_alpha_one_tracks_latest():
    e = Ewma(alpha=1.0)
    e.update(1.0)
    assert e.update(7.0) == 7.0


@given(
    alpha=st.floats(min_value=0.01, max_value=1.0),
    xs=st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=1, max_size=200),
)
def test_ewma_stays_within_input_bounds(alpha, xs):
    e = Ewma(alpha=alpha)
    for x in xs:
        e.update(x)
    assert min(xs) - 1e-6 <= e.value <= max(xs) + 1e-6


def test_ewma_rejects_bad_alpha():
    with pytest.raises(ValueError):
        Ewma(alpha=0.0)
    with pytest.raises(ValueError):
        Ewma(alpha=1.5)


from signal_control.conditioners import SchmittHysteresis


def test_hysteresis_trips_high_clears_low():
    h = SchmittHysteresis(trip_high=10.0, clear_low=4.0)
    assert h.update(9.9) is False  # below trip
    assert h.update(10.0) is True  # trips
    assert h.update(5.0) is True  # in the band -> stays tripped
    assert h.update(4.0) is False  # clears at/below clear_low


def test_hysteresis_rejects_inverted_band():
    with pytest.raises(ValueError):
        SchmittHysteresis(trip_high=4.0, clear_low=10.0)


@given(
    xs=st.lists(st.floats(min_value=4.0001, max_value=9.9999), min_size=1, max_size=100)
)
def test_hysteresis_never_flaps_inside_the_band(xs):
    # Values strictly inside (clear_low, trip_high) must never change state.
    h = SchmittHysteresis(trip_high=10.0, clear_low=4.0)
    start = h.tripped
    for x in xs:
        assert h.update(x) is start


from signal_control.conditioners import Persistence


def test_persistence_requires_k_consecutive():
    p = Persistence(k=3)
    assert p.update(True) is False
    assert p.update(True) is False
    assert p.update(True) is True
    assert p.update(False) is False  # reset
    assert p.update(True) is False


def test_persistence_rejects_bad_k():
    with pytest.raises(ValueError):
        Persistence(k=0)


@given(
    n=st.integers(min_value=1, max_value=50), k=st.integers(min_value=1, max_value=10)
)
def test_persistence_fires_iff_streak_reaches_k(n, k):
    p = Persistence(k=k)
    fired = [p.update(True) for _ in range(n)]
    assert all(fired[i] == (i + 1 >= k) for i in range(n))


from signal_control.conditioners import Cusum


def test_cusum_ignores_zero_mean_noise():
    c = Cusum(threshold=5.0, slack=0.5)
    # Alternating +/-1 around mean 0 never accumulates past the slack.
    fired = [c.update(1.0 if i % 2 == 0 else -1.0, mean=0.0) for i in range(200)]
    assert not any(fired)


def test_cusum_fires_on_sustained_upward_shift():
    c = Cusum(threshold=5.0, slack=0.5)
    fired = [c.update(2.0, mean=0.0) for _ in range(10)]  # sustained +2 vs mean 0
    assert any(fired)


def test_cusum_resets_after_firing():
    c = Cusum(threshold=3.0, slack=0.0)
    for _ in range(10):
        c.update(2.0, mean=0.0)
    # after a fire, accumulators are cleared
    assert c.pos == 0.0 and c.neg == 0.0


@given(
    threshold=st.floats(min_value=0.1, max_value=100.0),
    xs=st.lists(st.floats(min_value=-0.4, max_value=0.4), min_size=1, max_size=200),
)
def test_cusum_never_fires_when_deviation_strictly_inside_slack(threshold, xs):
    # slack=0.5 with |dev| <= 0.4: dev - slack < 0 and dev + slack > 0 on every
    # step, so both accumulators are driven back toward (and clamped at) zero
    # and can never cross +/-threshold, regardless of threshold's value.
    c = Cusum(threshold=threshold, slack=0.5)
    fired = [c.update(x, mean=0.0) for x in xs]
    assert not any(fired)
    assert c.pos == 0.0
    assert c.neg == 0.0


@given(
    slack=st.floats(min_value=0.0, max_value=5.0),
    threshold=st.floats(min_value=0.1, max_value=20.0),
    delta=st.floats(min_value=0.1, max_value=5.0),
)
def test_cusum_fires_eventually_on_sustained_shift_beyond_slack(
    slack, threshold, delta
):
    # A constant shift strictly greater than slack grows the positive
    # accumulator by exactly `delta` per step (dev - slack == delta > 0), so
    # it is guaranteed to exceed `threshold` within ceil(threshold/delta)+1
    # steps -- compute a safe upper bound and assert it fires by then.
    shift = slack + delta
    c = Cusum(threshold=threshold, slack=slack)
    steps = math.ceil(threshold / delta) + 2
    fired = [c.update(shift, mean=0.0) for _ in range(steps)]
    assert any(fired)


from signal_control.conditioners import AdaptiveThreshold


def test_adaptive_threshold_insufficient_history_is_not_anomalous():
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    assert at.is_anomalous(1000.0, baseline=[1.0, 2.0, 3.0]) is False


def test_adaptive_threshold_flags_robust_outlier():
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    baseline = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1]
    assert at.is_anomalous(50.0, baseline) is True
    assert at.is_anomalous(10.3, baseline) is False


def test_adaptive_threshold_ignores_single_outlier_in_baseline():
    # MAD is robust: one wild value in the baseline must not blow up the scale.
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    baseline = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 999.0]
    assert at.is_anomalous(20.0, baseline) is True


@given(
    baseline=st.lists(
        st.floats(
            min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
        ),
        min_size=8,
        max_size=30,
    ),
    d1=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    d2=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_adaptive_threshold_monotonic_in_distance_from_median(baseline, d1, d2):
    # The decision is abs(x - median) / robust_sigma >= z: for a fixed
    # baseline (so a fixed median and robust_sigma), the score is monotonic
    # non-decreasing in the distance from the median. So the point farther
    # from the median can never be *less* anomalous than the closer one.
    at = AdaptiveThreshold(z=2.0, min_samples=8)
    near, far = min(d1, d2), max(d1, d2)
    med = statistics.median(baseline)
    x_near = med + near
    x_far = med + far
    if at.is_anomalous(x_near, baseline):
        assert at.is_anomalous(x_far, baseline)


from signal_control.conditioners import Corroborator


def test_corroborator_confirms_when_all_probes_true():
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return True

    c = Corroborator(probe=probe, required=3)
    assert c.confirm() is True
    assert calls["n"] == 3


def test_corroborator_short_circuits_on_first_false():
    seq = iter([True, False, True])
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return next(seq)

    c = Corroborator(probe=probe, required=3)
    assert c.confirm() is False
    assert calls["n"] == 2  # stopped at the False


def test_corroborator_rejects_bad_required():
    with pytest.raises(ValueError):
        Corroborator(probe=lambda: True, required=0)


@given(data=st.data())
def test_corroborator_confirm_calls_probe_at_most_required_times(data):
    # For any boolean probe sequence, confirm() must call probe() at most
    # `required` times (the all(...) generator is capped by range(required)
    # and short-circuits on the first False), and its result must equal
    # all(...) over exactly the first `required` observations.
    bools = data.draw(st.lists(st.booleans(), min_size=1, max_size=20))
    required = data.draw(st.integers(min_value=1, max_value=len(bools)))
    calls = {"n": 0}
    it = iter(bools)

    def probe() -> bool:
        calls["n"] += 1
        return next(it)

    c = Corroborator(probe=probe, required=required)
    result = c.confirm()

    assert calls["n"] <= required
    assert result == all(bools[:required])

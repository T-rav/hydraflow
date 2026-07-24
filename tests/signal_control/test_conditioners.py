from __future__ import annotations

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

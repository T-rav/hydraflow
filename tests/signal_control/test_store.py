from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from signal_control.store import HistoricSignalStore


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_record_and_window():
    s = HistoricSignalStore(clock=FakeClock())
    for v in (1.0, 2.0, 3.0):
        s.record("x", v)
    assert s.window("x") == [1.0, 2.0, 3.0]
    assert s.window("unknown") == []


def test_ring_buffer_bounded_by_max_len():
    s = HistoricSignalStore(max_len=3, clock=FakeClock())
    for v in range(6):
        s.record("x", float(v))
    assert s.window("x") == [3.0, 4.0, 5.0]  # oldest dropped


def test_age_pruning():
    clk = FakeClock()
    s = HistoricSignalStore(max_age_s=10.0, clock=clk)
    s.record("x", 1.0)
    clk.advance(20.0)
    s.record("x", 2.0)  # recording prunes the stale 1.0
    assert s.window("x") == [2.0]


def test_reads():
    s = HistoricSignalStore(clock=FakeClock())
    for v in (2.0, 4.0, 6.0, 8.0):
        s.record("x", v)
    assert s.mean("x") == 5.0
    assert s.count_where("x", lambda v: v > 4.0) == 2
    assert s.ewma("x", alpha=1.0) == 8.0
    assert s.slope("x") == 2.0  # perfectly linear step of 2
    assert s.mean("missing") is None


@given(
    values=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=200,
    ),
    max_len=st.integers(min_value=1, max_value=32),
)
def test_ring_buffer_length_and_window_bounded_by_max_len(values, max_len):
    # Core ring-buffer invariant: regardless of how many values are recorded,
    # the buffer never holds more than max_len samples, and what it does hold
    # is exactly the *last* max_len values recorded, in original order. A
    # constant FakeClock means no age-pruning can interfere with this bound.
    s = HistoricSignalStore(max_len=max_len, clock=FakeClock())
    for v in values:
        s.record("signal", v)

    expected = values[-max_len:] if values else []
    assert len(s.window("signal")) == min(len(values), max_len)
    assert s.window("signal") == expected

from __future__ import annotations

from pathlib import Path

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


def test_jsonl_round_trip(tmp_path: Path):
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    s1 = HistoricSignalStore(clock=clk, path=p)
    s1.record("x", 1.0, tags={"k": "v"})
    s1.record("x", 2.0)
    # New store over the same file reloads history.
    s2 = HistoricSignalStore(clock=clk, path=p)
    assert s2.window("x") == [1.0, 2.0]


def test_reload_prunes_by_age(tmp_path: Path):
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    s1 = HistoricSignalStore(max_age_s=10.0, clock=clk, path=p)
    s1.record("x", 1.0)
    clk.advance(100.0)
    s2 = HistoricSignalStore(max_age_s=10.0, clock=clk, path=p)
    assert s2.window("x") == []  # stale sample dropped on reload


def test_in_memory_when_no_path(tmp_path: Path):
    s = HistoricSignalStore(clock=FakeClock(), path=None)
    s.record("x", 1.0)
    assert not list(tmp_path.iterdir())  # nothing written


def test_reload_skips_corrupt_lines(tmp_path: Path):
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    p.write_text(
        "not json at all\n"
        '{"signal": "x", "ts": 0.0, "value": 1.0, "tags": {}}\n'
        '{"signal": "x", "value": "oops"}\n'
        "\n",
        encoding="utf-8",
    )
    s = HistoricSignalStore(clock=clk, path=p)
    assert s.window("x") == [1.0]


def test_reload_survives_missing_signal_and_bad_tags(tmp_path: Path):
    # Binding requirement: _reload() must NEVER crash construction on a
    # corrupt line, even when the line is valid JSON with parseable ts/value
    # but a missing "signal" key or a non-dict-convertible "tags" value.
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    p.write_text(
        '{"ts": 5.0, "value": 3.0}\n'  # missing "signal" -> KeyError if unguarded
        '{"signal": "x", "ts": 1.0, "value": 1.0}\n'  # valid line
        '{"signal": "x", "ts": 5.0, "value": 1.0, "tags": "oops"}\n'  # bad tags -> ValueError
        "\n",
        encoding="utf-8",
    )
    s = HistoricSignalStore(clock=clk, path=p)  # must not raise
    assert s.window("x") == [1.0]  # only the valid line contributed

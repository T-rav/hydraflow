import pytest
from hypothesis import given
from hypothesis import strategies as st

from auto_tighten.engine import MonotoneViolation, TighteningEngine
from auto_tighten.models import Observation
from tests.auto_tighten.test_ratchet_adapter import _FakeAdapter


def test_confirm_never_returns_a_non_tightening_floor():
    eng, a = TighteningEngine(), _FakeAdapter()
    # A window that is all BELOW baseline must never yield a floor.
    below = [
        Observation(
            ts="t", ratchet_id="fake", current=60.0, baseline=70.0, direction="looser"
        )
    ] * 5
    assert eng.confirm(a, below, baseline=70.0, stability_ticks=3) is None


def test_guard_rejects_non_tightening_actuation():
    eng, a = TighteningEngine(), _FakeAdapter()
    with pytest.raises(MonotoneViolation):
        eng.guard_is_tighter(
            a, candidate=65.0, baseline=70.0
        )  # 65 < 70 for coverage: not tighter


_PCT = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


@given(
    window_vals=st.lists(_PCT, min_size=0, max_size=10),
    baseline=_PCT,
    stability_ticks=st.integers(min_value=1, max_value=8),
)
def test_confirm_never_yields_a_non_tightening_floor_property(
    window_vals: list[float], baseline: float, stability_ticks: int
) -> None:
    # Monotone-tighten property: over ANY window / baseline / ticks, confirm
    # either holds (returns None) or returns a floor STRICTLY tighter than
    # baseline. It can never return a value that would lower the gate.
    eng, a = TighteningEngine(), _FakeAdapter()
    window = [
        Observation(
            ts="t", ratchet_id="fake", current=v, baseline=baseline, direction="?"
        )
        for v in window_vals
    ]
    result = eng.confirm(a, window, baseline=baseline, stability_ticks=stability_ticks)
    if result is not None:
        assert a.is_tighter(result, baseline)


@given(candidate=_PCT, baseline=_PCT)
def test_guard_raises_exactly_when_not_tightening_property(
    candidate: float, baseline: float
) -> None:
    # The actuation gate can't be bypassed: guard_is_tighter raises iff the
    # candidate is NOT strictly tighter than baseline.
    eng, a = TighteningEngine(), _FakeAdapter()
    if a.is_tighter(candidate, baseline):
        eng.guard_is_tighter(a, candidate, baseline)  # must not raise
    else:
        with pytest.raises(MonotoneViolation):
            eng.guard_is_tighter(a, candidate, baseline)

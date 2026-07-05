import pytest

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

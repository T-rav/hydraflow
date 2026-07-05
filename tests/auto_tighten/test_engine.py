from auto_tighten.engine import TighteningEngine
from auto_tighten.models import Observation
from tests.auto_tighten.test_ratchet_adapter import (
    _FakeAdapter,  # reuse the scalar coverage-like adapter
)


def _obs(v):
    return Observation(
        ts="t", ratchet_id="fake", current=v, baseline=70.0, direction="tighter"
    )


def test_classify_directions():
    eng, a = TighteningEngine(), _FakeAdapter()
    assert eng.classify(a, 80.0, 70.0) == "tighter"
    assert eng.classify(a, 60.0, 70.0) == "looser"
    assert eng.classify(a, 70.0, 70.0) == "same"


def test_confirm_uses_weakest_in_window_then_margin():
    eng, a = TighteningEngine(), _FakeAdapter()
    # window readings 80, 78, 82 -> weakest (min) = 78 -> margin 1 -> 77.0 (> baseline 70)
    floor = eng.confirm(
        a, [_obs(80.0), _obs(78.0), _obs(82.0)], baseline=70.0, stability_ticks=3
    )
    assert floor == 77.0


def test_confirm_holds_below_stability_ticks():
    eng, a = TighteningEngine(), _FakeAdapter()
    assert (
        eng.confirm(a, [_obs(80.0), _obs(80.0)], baseline=70.0, stability_ticks=3)
        is None
    )


def test_confirm_holds_when_margin_erases_gain():
    eng, a = TighteningEngine(), _FakeAdapter()
    # weakest 70.5 -> margin 1 -> 69.5, not > baseline 70 -> hold
    assert (
        eng.confirm(
            a, [_obs(70.5), _obs(71.0), _obs(72.0)], baseline=70.0, stability_ticks=3
        )
        is None
    )

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from signal_control.controllers import AimdController


def test_aimd_multiplicative_decrease_on_breach():
    a = AimdController(lo=1, hi=16, start=16, decrease_factor=0.5)
    assert a.update(breached=True, headroom=False) == 8
    assert a.update(breached=True, headroom=False) == 4


def test_aimd_additive_increase_after_sustained_headroom():
    a = AimdController(lo=1, hi=16, start=4, increase_step=1, hold_ticks=3)
    assert a.update(breached=False, headroom=True) == 4  # streak 1
    assert a.update(breached=False, headroom=True) == 4  # streak 2
    assert a.update(breached=False, headroom=True) == 5  # streak 3 -> +1
    assert a.update(breached=False, headroom=True) == 5  # streak resets, back to 1


def test_aimd_neutral_tick_resets_headroom_streak():
    a = AimdController(lo=1, hi=16, start=4, hold_ticks=2)
    a.update(breached=False, headroom=True)  # streak 1
    a.update(breached=False, headroom=False)  # neutral -> reset
    assert a.update(breached=False, headroom=True) == 4  # streak 1 again, no bump


@given(
    steps=st.lists(st.tuples(st.booleans(), st.booleans()), min_size=1, max_size=300),
)
def test_aimd_cap_always_within_bounds(steps):
    a = AimdController(lo=1, hi=8, start=8)
    for breached, headroom in steps:
        cap = a.update(breached=breached, headroom=headroom)
        assert 1 <= cap <= 8


def test_aimd_rejects_bad_bounds():
    with pytest.raises(ValueError):
        AimdController(lo=5, hi=1, start=3)
    with pytest.raises(ValueError):
        AimdController(lo=1, hi=8, start=99)

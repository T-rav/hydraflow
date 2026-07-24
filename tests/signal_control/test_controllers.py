from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from signal_control.controllers import (
    AimdController,
    PidController,
    RetryController,
    RetryOutcome,
    RetryStatus,
)


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


def test_pid_proportional_response_sign():
    pid = PidController(kp=1.0, ki=0.0, kd=0.0, out_lo=-10.0, out_hi=10.0)
    assert pid.update(3.0) == 3.0
    assert pid.update(-3.0) == -3.0


def test_pid_output_clamped_to_bounds():
    pid = PidController(kp=100.0, ki=0.0, kd=0.0, out_lo=-5.0, out_hi=5.0)
    assert pid.update(1.0) == 5.0
    assert pid.update(-1.0) == -5.0


@given(
    errors=st.lists(st.floats(min_value=-1e3, max_value=1e3), min_size=1, max_size=300)
)
def test_pid_output_always_within_bounds_and_no_windup(errors):
    pid = PidController(kp=0.5, ki=0.2, kd=0.1, out_lo=0.0, out_hi=10.0)
    for e in errors:
        out = pid.update(e)
        assert 0.0 <= out <= 10.0
    # anti-windup: after a long positive saturation, one big negative error
    # must bring the output off the ceiling within a bounded number of steps.
    for _ in range(1000):
        pid.update(100.0)  # saturate high
    assert pid.update(-100.0) < 10.0


@pytest.mark.asyncio
async def test_retry_stops_on_success():
    async def attempt(n: int) -> RetryOutcome:
        return RetryOutcome(RetryStatus.SUCCESS)

    r = await RetryController(max_attempts=2).run(attempt)
    assert r.succeeded is True and r.attempts == 1 and r.terminal is False


@pytest.mark.asyncio
async def test_retry_exhausts_then_gives_up():
    calls = {"n": 0}

    async def attempt(n: int) -> RetryOutcome:
        calls["n"] += 1
        return RetryOutcome(RetryStatus.RETRYABLE, detail=f"try {n}")

    r = await RetryController(max_attempts=2).run(attempt)
    assert r.succeeded is False and r.attempts == 2 and r.terminal is False
    assert calls["n"] == 2
    assert [o.detail for o in r.history] == ["try 1", "try 2"]


@pytest.mark.asyncio
async def test_retry_short_circuits_on_terminal():
    calls = {"n": 0}

    async def attempt(n: int) -> RetryOutcome:
        calls["n"] += 1
        return RetryOutcome(RetryStatus.TERMINAL, detail="hard conflict")

    r = await RetryController(max_attempts=5).run(attempt)
    assert r.succeeded is False and r.terminal is True and r.attempts == 1
    assert calls["n"] == 1  # did not burn remaining attempts


def test_retry_rejects_bad_max_attempts():
    with pytest.raises(ValueError):
        RetryController(max_attempts=0)


@settings(max_examples=50)
@given(
    outcomes=st.lists(st.sampled_from(list(RetryStatus)), min_size=0, max_size=15),
    max_attempts=st.integers(min_value=1, max_value=10),
)
@pytest.mark.asyncio
async def test_retry_property_bounded_and_stops_at_first_terminal_event(
    outcomes, max_attempts
):
    """Property: run() never exceeds max_attempts, stops at the first
    SUCCESS/TERMINAL, and attempts always equals len(history).

    A hypothesis-generated sequence of statuses is popped one-per-attempt;
    once exhausted, further attempts report RETRYABLE (so a short generated
    sequence still lets the controller run out its full budget).
    """
    sequence = list(outcomes)

    async def attempt(n: int) -> RetryOutcome:
        status = sequence.pop(0) if sequence else RetryStatus.RETRYABLE
        return RetryOutcome(status, detail=f"attempt-{n}")

    result = await RetryController(max_attempts=max_attempts).run(attempt)

    # Bound: never more than max_attempts, and attempts always matches history.
    assert result.attempts <= max_attempts
    assert result.attempts == len(result.history)

    # First-stop semantics: only the last recorded outcome may be
    # SUCCESS/TERMINAL — everything before it must have been RETRYABLE.
    for outcome in result.history[:-1]:
        assert outcome.status is RetryStatus.RETRYABLE

    last = result.history[-1]
    if result.succeeded:
        assert last.status is RetryStatus.SUCCESS
    elif result.terminal:
        assert last.status is RetryStatus.TERMINAL
    else:
        # Neither succeeded nor terminal -> the budget ran out.
        assert result.attempts == max_attempts
        assert last.status is RetryStatus.RETRYABLE

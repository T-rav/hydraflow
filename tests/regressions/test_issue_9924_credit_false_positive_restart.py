"""Regression: a non-corroborated credit signal orphaned the crashed loop,
hot-looping the supervisor and killing the phase (#9924).

``_pause_for_credits``'s "not corroborated / false positive" branch returned
without recreating the crashed loop's task. The completed-with-exception task
stayed in ``_supervise_loops``'s ``tasks`` dict, so the supervisor re-observed
the same dead task every iteration → re-ran the credit handler in a tight hot
loop (an alert storm, ~9 WARNING lines in one second) and left the phase (e.g.
``plan``) permanently dead — no restart ever happened. The alert storm is what
prompted the operator "Stop" that took the whole factory (all repos) down.

The fix: ``_pause_for_credits`` returns whether it paused; on a false positive
``_handle_credit_exhaustion`` restarts the loop via ``_restart_loop`` — exactly
like any other transient crash — so the task is recreated (no orphan, no hot
loop, no dead phase), bounded by the poll interval on the next cycle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError


async def _noop_loop() -> None:
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_false_positive_restarts_loop_not_orphaned(config) -> None:
    """Probe says available → the crashed loop's task is RECREATED, not orphaned."""
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]

    old = asyncio.create_task(_noop_loop())
    await old  # simulate the crashed-and-completed 'plan' task
    tasks: dict[str, asyncio.Task[None]] = {"plan": old}
    factories: list = [("plan", _noop_loop)]
    exc = CreditExhaustedError("Your credit balance is too low")

    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=True)):
        await orch._handle_credit_exhaustion(exc, "plan", tasks, factories)

    assert tasks["plan"] is not old  # restarted — not left pointing at the dead task
    assert orch._credits_paused_until is None  # no global pause committed
    tasks["plan"].cancel()
    await asyncio.gather(tasks["plan"], return_exceptions=True)


@pytest.mark.asyncio
async def test_pause_for_credits_returns_false_on_false_positive(config) -> None:
    """``_pause_for_credits`` reports False (not paused) when the probe says available."""
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    factories: list = [("plan", _noop_loop)]
    exc = CreditExhaustedError("usage limit reached")

    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=True)):
        paused = await orch._pause_for_credits(exc, "plan", {}, factories)

    assert paused is False


@pytest.mark.asyncio
async def test_pause_for_credits_returns_true_on_real_exhaustion(config) -> None:
    """``_pause_for_credits`` reports True (paused) when the probe confirms exhaustion."""
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    orch._sleep_until_resume = AsyncMock()  # type: ignore[method-assign]
    orch._resume_loops_after_credit_pause = AsyncMock()  # type: ignore[method-assign]
    factories: list = [("plan", _noop_loop)]
    exc = CreditExhaustedError("usage limit reached")

    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=False)):
        paused = await orch._pause_for_credits(exc, "plan", {}, factories)

    assert paused is True

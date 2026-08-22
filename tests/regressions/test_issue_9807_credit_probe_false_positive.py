"""Regression: a false credit signal triggered a 5-hour GLOBAL pause (#9807,
fixed in #9869).

``is_credit_exhaustion`` matches credit-error *prose*, so a diagnostic/reviewer
run that merely quoted a prior cap in its analysis raised ``CreditExhaustedError``
and ``_pause_for_credits`` cancelled every loop for hours — while credits were
actually fine.

The fix corroborates the text-detected signal with a live API probe before
committing a global pause: if ``probe_credit_availability`` reports credits are
available, the signal is treated as a false positive and **no pause is
committed**. This pins that behaviour (and the kill-switch that reverts it).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError


@pytest.mark.asyncio
async def test_false_credit_signal_not_paused_when_probe_says_available(config) -> None:
    """Quoted credit-error prose (probe reports available) must NOT pause."""
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    tasks: dict[str, asyncio.Task[None]] = {}
    factories: list = [("plan", AsyncMock())]
    exc = CreditExhaustedError("Your credit balance is too low")

    with patch("orchestrator_credits.probe_credit_availability", AsyncMock(return_value=True)):
        await orch._pause_for_credits(exc, "diagnostic", tasks, factories)

    assert orch._credits_paused_until is None  # no global pause committed
    orch._cancel_all_loops_and_runners.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_credit_out_still_pauses_when_probe_confirms(config) -> None:
    """A genuine cap (probe reports exhausted) must still pause."""
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    orch._sleep_until_resume = AsyncMock()  # type: ignore[method-assign]
    orch._resume_loops_after_credit_pause = AsyncMock()  # type: ignore[method-assign]
    tasks: dict[str, asyncio.Task[None]] = {}
    factories: list = [("plan", AsyncMock())]
    exc = CreditExhaustedError("usage limit reached")

    with patch("orchestrator_credits.probe_credit_availability", AsyncMock(return_value=False)):
        await orch._pause_for_credits(exc, "plan", tasks, factories)

    assert orch._credits_paused_until is not None  # pause committed
    orch._cancel_all_loops_and_runners.assert_awaited_once()

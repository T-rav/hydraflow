"""Regression: false-positive credit suppression flooded alerts + spun (#9888).

After #9869's probe corroboration, a loop repeatedly raising a FALSE
CreditExhaustedError (quoted prose) spun: probe → banner → immediate loop
restart → re-raise. Observed six "NOT corroborated" SYSTEM_ALERTs in 3ms.

Pins:
1. Within the cooldown, repeat signals from the same source are log-only —
   no probe call, no banner.
2. After the cooldown expires, suppression (probe + single banner) resumes.
3. A suppressed-credit restart delays the loop body inside the recreated
   task (supervisor never blocked, task tracked).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from events import EventType
from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError


def _alert_count(bus_mock) -> int:
    return sum(
        1
        for call in bus_mock.publish.await_args_list
        if call.args[0].type is EventType.SYSTEM_ALERT
    )


@pytest.mark.asyncio
async def test_repeat_false_positives_within_cooldown_are_log_only(config) -> None:
    orch = HydraFlowOrchestrator(config)
    orch._bus = AsyncMock()
    exc = CreditExhaustedError("Your credit balance is too low")
    probe = AsyncMock(return_value=True)

    with patch("orchestrator.probe_credit_availability", probe):
        for _ in range(6):  # the observed 6-in-3ms storm
            paused = await orch._pause_for_credits(exc, "diagnostic", {}, [])
            assert paused is False

    assert probe.await_count == 1  # only the first signal probed
    assert _alert_count(orch._bus) == 1  # exactly one banner
    assert orch._credits_paused_until is None


@pytest.mark.asyncio
async def test_cooldown_expiry_resumes_suppression_banner(config) -> None:
    orch = HydraFlowOrchestrator(config)
    orch._bus = AsyncMock()
    exc = CreditExhaustedError("usage limit reached")
    probe = AsyncMock(return_value=True)

    with patch("orchestrator.probe_credit_availability", probe):
        await orch._pause_for_credits(exc, "diagnostic", {}, [])
        # Backdate the suppression past the cooldown (clock-free test).
        orch._credit_fp_last["diagnostic"] = datetime.now(UTC) - timedelta(
            seconds=config.credit_fp_suppress_cooldown_seconds + 1
        )
        await orch._pause_for_credits(exc, "diagnostic", {}, [])

    assert probe.await_count == 2
    assert _alert_count(orch._bus) == 2


@pytest.mark.asyncio
async def test_sources_are_throttled_independently(config) -> None:
    orch = HydraFlowOrchestrator(config)
    orch._bus = AsyncMock()
    exc = CreditExhaustedError("credit balance too low")
    probe = AsyncMock(return_value=True)

    with patch("orchestrator.probe_credit_availability", probe):
        await orch._pause_for_credits(exc, "diagnostic", {}, [])
        await orch._pause_for_credits(exc, "reviewer", {}, [])

    assert probe.await_count == 2  # per-source cooldowns


@pytest.mark.asyncio
async def test_restart_delay_runs_inside_the_recreated_task(config) -> None:
    orch = HydraFlowOrchestrator(config)
    orch._bus = AsyncMock()
    started = asyncio.Event()

    async def factory() -> None:
        started.set()

    tasks: dict[str, asyncio.Task[None]] = {}
    await orch._restart_loop(
        "diagnostic",
        RuntimeError("x"),
        tasks,
        [("diagnostic", factory)],
        restart_delay=0.05,
    )

    assert "diagnostic" in tasks  # tracked immediately — supervisor not blocked
    assert not started.is_set()  # loop body has NOT run yet
    await asyncio.wait_for(tasks["diagnostic"], timeout=2)
    assert started.is_set()

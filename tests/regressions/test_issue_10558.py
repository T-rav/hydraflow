"""Regression: a genuine weekly-limit exhaustion must PAUSE the factory, not be
discarded as a false positive by a probe that structurally cannot detect it
(#10558).

Background
----------
The credit-pause corroboration (#9807/#9924) runs a live auth/availability probe
to reject false credit signals scanned from an agent's *analysis prose* — a
diagnostic/reviewer run that merely quotes a prior cap in its output (the #9895
``CREDIT_PROSE_SCAN`` class). But that probe checks auth/availability, NOT the
*weekly* quota: with the Anthropic weekly limit exhausted, the key is still valid
and the probe passes. So a GENUINE weekly-limit signal coming straight from the
CLI's own termination was discarded as "likely quoted prose"; the factory never
paused (``credits_paused_until`` stayed ``None``); and every core loop
crash-restarted in a tight loop against an exhausted billing signal, burning the
already-exhausted budget and eventually wedging the orchestrator.

Fix
---
Distinguish the signal's *origin*, not just corroborate its text.
``CreditExhaustedError.authoritative`` is ``True`` when the signal came from the
CLI's own stderr / a structured API error (the process's direct termination) and
``False`` only when it was scanned from agent stdout prose. ``_pause_for_credits``
gates the probe/cooldown corroboration on ``not authoritative``: an authoritative
signal pauses directly (the probe is demonstrably blind to weekly limits); a
prose-derived signal keeps the full #9895/#9807 false-positive protection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from events import EventType
from orchestrator import HydraFlowOrchestrator
from runner_utils import StreamConfig, stream_claude_process
from subprocess_util import CreditExhaustedError
from tests.helpers import make_streaming_proc

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

WEEKLY_MSG = "You've hit your weekly limit · resets Jul 29 at 5pm"


async def _noop_loop() -> None:
    await asyncio.sleep(0)


def _stream_kwargs(event_bus: EventBus, **config_overrides: object) -> dict[str, object]:
    """Minimal kwargs for :func:`stream_claude_process` (mirrors test_credit_pause)."""
    return {
        "cmd": ["claude", "-p"],
        "prompt": "test prompt",
        "cwd": Path("/tmp/test"),
        "active_procs": set(),
        "event_bus": event_bus,
        "event_data": {"issue": 1},
        "logger": logging.getLogger("test-10558"),
        "config": StreamConfig(**config_overrides),  # type: ignore[arg-type]
    }


# ---------------------------------------------------------------------------
# Orchestrator: authoritative signals pause; prose-derived ones stay gated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authoritative_weekly_limit_pauses_despite_probe_available(
    config: HydraFlowConfig, event_bus: EventBus
) -> None:
    """A CLI-origin weekly-limit signal PAUSES even though the auth probe (blind to
    weekly limits) reports the key is fine — the probe must not gate it (#10558)."""
    orch = HydraFlowOrchestrator(config, event_bus=event_bus)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    orch._sleep_until_resume = AsyncMock()  # type: ignore[method-assign]
    orch._resume_loops_after_credit_pause = AsyncMock()  # type: ignore[method-assign]
    factories: list = [("plan", _noop_loop)]
    resume = datetime.now(UTC) + timedelta(hours=72)
    exc = CreditExhaustedError(WEEKLY_MSG, resume_at=resume, authoritative=True)

    with patch(
        "orchestrator.probe_credit_availability", AsyncMock(return_value=True)
    ) as probe:
        paused = await orch._pause_for_credits(exc, "plan", {}, factories)

    assert paused is True
    assert orch._credits_paused_until is not None
    # The blind auth probe must be skipped entirely for an authoritative signal.
    probe.assert_not_awaited()

    alerts = [e for e in event_bus.get_history() if e.type == EventType.SYSTEM_ALERT]
    pause_alerts = [e for e in alerts if "resume_at" in e.data]
    assert pause_alerts, "expected a credit-pause SYSTEM_ALERT carrying resume_at"
    messages = " ".join(str(e.data.get("message", "")) for e in alerts).lower()
    assert "not corroborated" not in messages


@pytest.mark.asyncio
async def test_prose_derived_signal_still_refuted_by_probe(
    config: HydraFlowConfig, event_bus: EventBus
) -> None:
    """A prose-scanned credit signal that the probe refutes still does NOT pause —
    the #9895/#9807 false-positive protection stays for quoted-prose signals."""
    orch = HydraFlowOrchestrator(config, event_bus=event_bus)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    factories: list = [("plan", _noop_loop)]
    exc = CreditExhaustedError("usage limit reached", authoritative=False)

    with patch(
        "orchestrator.probe_credit_availability", AsyncMock(return_value=True)
    ) as probe:
        paused = await orch._pause_for_credits(exc, "plan", {}, factories)

    assert paused is False
    assert orch._credits_paused_until is None
    probe.assert_awaited()  # a prose-derived signal IS corroborated

    alerts = [e for e in event_bus.get_history() if e.type == EventType.SYSTEM_ALERT]
    assert any(
        "not corroborated" in str(e.data.get("message", "")).lower() for e in alerts
    ), "expected the false-positive 'not corroborated' warning alert"


# ---------------------------------------------------------------------------
# Runner: origin classification (stderr = authoritative, stdout prose = not).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stderr_origin_weekly_signal_is_authoritative(
    event_bus: EventBus,
) -> None:
    """When the CLI's own stderr carries the weekly-limit signal, the raised
    error is authoritative so the orchestrator pauses without probing."""
    mock_create = make_streaming_proc(
        returncode=1,
        stdout="working on the task...",
        stderr=WEEKLY_MSG,
    )
    with (
        patch("asyncio.create_subprocess_exec", mock_create),
        pytest.raises(CreditExhaustedError) as exc_info,
    ):
        await stream_claude_process(**_stream_kwargs(event_bus))

    assert exc_info.value.authoritative is True


@pytest.mark.asyncio
async def test_stdout_prose_only_signal_is_not_authoritative(
    event_bus: EventBus,
) -> None:
    """When only agent stdout prose (clean stderr) carries the credit phrase, the
    raised error is NOT authoritative so the orchestrator's probe still gates it."""
    mock_create = make_streaming_proc(
        returncode=0,
        stdout="Diagnosis: the earlier run failed because you've hit your weekly limit.",
        stderr="",
    )
    with (
        patch("asyncio.create_subprocess_exec", mock_create),
        pytest.raises(CreditExhaustedError) as exc_info,
    ):
        await stream_claude_process(**_stream_kwargs(event_bus))

    assert exc_info.value.authoritative is False

"""Orchestrator credit-failover: engage on a Claude cap + switch-back probe (#10844)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import credit_failover
from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError


async def _noop_loop() -> None:
    await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _reset_failover() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _auth_claude_cap() -> CreditExhaustedError:
    return CreditExhaustedError(
        "weekly limit reached", provider="anthropic", authoritative=True
    )


# --- engage -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_authoritative_claude_cap_engages_failover_not_pause(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    orch = HydraFlowOrchestrator(config)
    orch._start_failover_probe = MagicMock()  # type: ignore[method-assign]
    old = asyncio.create_task(_noop_loop())
    await old
    tasks: dict[str, asyncio.Task[None]] = {"plan": old}
    await orch._handle_credit_exhaustion(
        _auth_claude_cap(), "plan", tasks, [("plan", _noop_loop)]
    )
    assert credit_failover.is_active() is True
    assert orch._credits_paused_until is None  # rerouted, NOT paused
    assert tasks["plan"] is not old  # crashed loop restarted (routes to GLM)
    orch._start_failover_probe.assert_called_once()
    tasks["plan"].cancel()
    await asyncio.gather(tasks["plan"], return_exceptions=True)


@pytest.mark.asyncio
async def test_prose_signal_does_not_engage_failover(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    orch._sleep_until_resume = AsyncMock()  # type: ignore[method-assign]
    orch._resume_loops_after_credit_pause = AsyncMock()  # type: ignore[method-assign]
    exc = CreditExhaustedError(
        "usage limit reached", provider="anthropic", authoritative=False
    )
    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=False)):
        await orch._handle_credit_exhaustion(exc, "plan", {}, [("plan", _noop_loop)])
    assert credit_failover.is_active() is False  # prose → normal pause, no failover
    assert orch._credits_paused_until is not None


@pytest.mark.asyncio
async def test_no_zai_key_does_not_engage(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
    orch = HydraFlowOrchestrator(config)
    assert await orch._maybe_engage_failover(_auth_claude_cap()) is False
    assert credit_failover.is_active() is False


@pytest.mark.asyncio
async def test_disabled_does_not_engage(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    object.__setattr__(config, "credit_failover_enabled", False)
    orch = HydraFlowOrchestrator(config)
    assert await orch._maybe_engage_failover(_auth_claude_cap()) is False


@pytest.mark.asyncio
async def test_zai_cap_does_not_engage_failover(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    orch = HydraFlowOrchestrator(config)
    exc = CreditExhaustedError(
        "insufficient balance", provider="zai", authoritative=True
    )
    assert await orch._maybe_engage_failover(exc) is False


@pytest.mark.asyncio
async def test_already_active_returns_true_and_arms_probe(
    config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    orch = HydraFlowOrchestrator(config)
    orch._start_failover_probe = MagicMock()  # type: ignore[method-assign]
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=15)
    before = credit_failover.status().probe_after
    assert await orch._maybe_engage_failover(_auth_claude_cap()) is True
    assert credit_failover.status().probe_after == before  # not re-engaged
    # This orchestrator ensures it has a live probe even when it did not engage.
    orch._start_failover_probe.assert_called_once()


@pytest.mark.asyncio
async def test_rearm_probe_on_startup_when_failover_active(config) -> None:
    """A restart while failed over must re-arm the switch-back probe (#10844)."""
    orch = HydraFlowOrchestrator(config)
    orch._start_failover_probe = MagicMock()  # type: ignore[method-assign]
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=15)
    orch._rearm_failover_probe_if_active()
    orch._start_failover_probe.assert_called_once()


@pytest.mark.asyncio
async def test_rearm_probe_noop_when_not_failed_over(config) -> None:
    orch = HydraFlowOrchestrator(config)
    orch._start_failover_probe = MagicMock()  # type: ignore[method-assign]
    orch._rearm_failover_probe_if_active()
    orch._start_failover_probe.assert_not_called()


# --- switch-back probe ------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_clears_failover_when_claude_available(config) -> None:
    orch = HydraFlowOrchestrator(config)
    credit_failover.engage(
        now=datetime.now(UTC) - timedelta(minutes=30),
        resume_at=None,
        cooldown_minutes=15,
    )  # probe_after in the past → due
    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=True)):
        cleared = await orch._probe_claude_for_switchback()
    assert cleared is True
    assert credit_failover.is_active() is False


@pytest.mark.asyncio
async def test_probe_advances_when_claude_still_capped(config) -> None:
    orch = HydraFlowOrchestrator(config)
    credit_failover.engage(
        now=datetime.now(UTC) - timedelta(minutes=30),
        resume_at=None,
        cooldown_minutes=15,
    )
    with patch("orchestrator.probe_credit_availability", AsyncMock(return_value=False)):
        cleared = await orch._probe_claude_for_switchback()
    assert cleared is False
    assert credit_failover.is_active() is True
    assert credit_failover.status().probe_after > datetime.now(UTC)  # pushed out


@pytest.mark.asyncio
async def test_probe_noop_before_due(config) -> None:
    orch = HydraFlowOrchestrator(config)
    credit_failover.engage(
        now=datetime.now(UTC), resume_at=None, cooldown_minutes=15
    )  # probe_after = +15m → not due
    probe = AsyncMock(return_value=True)
    with patch("orchestrator.probe_credit_availability", probe):
        cleared = await orch._probe_claude_for_switchback()
    assert cleared is False
    probe.assert_not_called()
    assert credit_failover.is_active() is True

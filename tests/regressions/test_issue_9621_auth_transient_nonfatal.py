"""Regression: a TRANSIENT GitHub auth/network blip stopped the whole factory (#9621).

On 2026-06-20 a momentary network/API blip in ``ci_monitor`` surfaced as an
``AuthenticationError`` (a gh call's stderr matched an auth pattern). That
propagated fatally: ``reraise_on_credit_or_bug`` re-raised it, ``_polling_loop``
re-raised it (auth is in its fatal tuple), the supervisor caught it in
``_handle_loop_exception`` and ``_handle_auth_error`` set ``_auth_failed`` +
``_stop_event`` — pausing ALL loops and stopping the orchestrator for ~2.5h,
until a manual ``POST /api/control/start``. The token was actually valid the
whole time; a restart recovered instantly.

The fix mirrors the credit-pause corroboration (#9807/#9924): before halting
the factory, ``_handle_auth_error`` corroborates the signal with a live
``gh auth status`` probe. If auth is actually fine, the signal is a transient
false positive → restart the crashed loop instead of stopping (non-fatal).
Only a probe-confirmed, persistent auth rejection halts the factory (fail-safe).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator import HydraFlowOrchestrator
from subprocess_util import AuthenticationError


async def _noop_loop() -> None:
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_transient_auth_blip_restarts_loop_not_stopped(config) -> None:
    """Probe says auth is fine → the crashed loop restarts; factory does NOT stop."""
    orch = HydraFlowOrchestrator(config)

    old = asyncio.create_task(_noop_loop())
    await old  # simulate the crashed-and-completed 'ci_monitor' task
    tasks: dict[str, asyncio.Task[None]] = {"ci_monitor": old}
    factories: list = [("ci_monitor", _noop_loop)]
    exc = AuthenticationError("Command ('gh', ...) failed: authentication required")

    with patch("orchestrator.probe_auth_availability", AsyncMock(return_value=True)):
        await orch._handle_loop_exception("ci_monitor", exc, tasks, factories)

    assert orch._auth_failed is False  # factory NOT marked auth-failed
    assert not orch._stop_event.is_set()  # factory NOT stopped
    assert tasks["ci_monitor"] is not old  # crashed loop was restarted, not orphaned
    tasks["ci_monitor"].cancel()
    await asyncio.gather(tasks["ci_monitor"], return_exceptions=True)


@pytest.mark.asyncio
async def test_persistent_auth_failure_still_stops(config) -> None:
    """Probe confirms auth is broken → factory still halts (fail-safe preserved)."""
    orch = HydraFlowOrchestrator(config)
    tasks: dict[str, asyncio.Task[None]] = {}
    factories: list = [("ci_monitor", _noop_loop)]
    exc = AuthenticationError("Command ('gh', ...) failed: not logged in")

    with patch("orchestrator.probe_auth_availability", AsyncMock(return_value=False)):
        await orch._handle_loop_exception("ci_monitor", exc, tasks, factories)

    assert orch._auth_failed is True  # factory marked auth-failed
    assert orch._stop_event.is_set()  # factory stopped


@pytest.mark.asyncio
async def test_kill_switch_reverts_to_halt_on_signal(config) -> None:
    """With the probe kill-switch off, any auth signal halts (legacy behaviour)."""
    config.auth_failure_require_probe = False
    orch = HydraFlowOrchestrator(config)
    tasks: dict[str, asyncio.Task[None]] = {}
    factories: list = [("ci_monitor", _noop_loop)]
    exc = AuthenticationError("transient blip")

    # Probe would say auth is fine, but the kill-switch disables corroboration.
    with patch(
        "orchestrator.probe_auth_availability", AsyncMock(return_value=True)
    ) as probe:
        await orch._handle_loop_exception("ci_monitor", exc, tasks, factories)

    probe.assert_not_awaited()  # short-circuited: probe never called
    assert orch._auth_failed is True
    assert orch._stop_event.is_set()

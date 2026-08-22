"""Loop crash triage and restart for :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorRestartMixin`.

One cohesive concern: what happens to a loop that died. The exception triage
that routes a crashed loop to the auth handler, the credit handler, or a plain
restart; the #9621 auth-signal corroboration probe that refuses to halt the
factory on a transient blip; the cancel-and-recreate used both on a crash and
by the operator-triggered ``restart_loop_task`` verb.

The supervisor that *detects* the crash — ``_supervise_loops`` and its
``loop_factories`` list — deliberately stays in ``orchestrator.py``: it is the
ADR-0001 concurrent-loop shape the P6.1 audit probe and the loop-wiring guards
read out of that file.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from models import ErrorPayload, SystemAlertPayload
from orchestrator_common import _AUTH_TRANSIENT_RESTART_DELAY_S
from subprocess_util import (
    AuthenticationError,
    CreditExhaustedError,
    probe_auth_availability,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorRestartMixin:
    """Loop crash triage and restart for :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _auth_failed: bool
    _bus: EventBus
    _config: HydraFlowConfig
    _loop_factories: dict[str, Callable[[], Coroutine[Any, Any, None]]]
    _loop_tasks: dict[str, asyncio.Task[None]]
    _stop_event: asyncio.Event

    if TYPE_CHECKING:

        async def _handle_credit_exhaustion(
            self,
            exc: CreditExhaustedError,
            loop_name: str,
            tasks: dict[str, asyncio.Task[None]],
            loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        ) -> None: ...  # provided by OrchestratorCreditsMixin

    async def _handle_auth_error(
        self,
        loop_name: str,
        exc: BaseException,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Corroborate the auth signal with a live probe before halting the factory.

        A single gh call's stderr can match an auth pattern during a transient
        network/API blip; that used to propagate fatally and stop ALL loops for
        hours (#9621 — a momentary blip stalled the factory ~2.5h; a restart
        recovered instantly because the token was fine the whole time).

        Mirror the credit-pause corroboration (#9807/#9924): probe live auth
        with ``gh auth status`` before committing a global halt. If auth is
        actually fine the signal is a transient false positive — restart the
        crashed loop (non-fatal, retried next tick) instead of stopping. Only a
        probe-confirmed, PERSISTENT auth rejection halts the factory (fail-safe).
        Kill-switch: ``auth_failure_require_probe=False`` reverts to
        halt-on-signal. ``and`` short-circuits so the probe is skipped when the
        kill-switch is off.
        """
        if self._config.auth_failure_require_probe and await probe_auth_availability():
            logger.warning(
                "GitHub auth-failure signal from %r NOT corroborated by a live "
                "`gh auth status` probe — treating as a transient blip; "
                "restarting the loop instead of pausing all loops (#9621).",
                loop_name,
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "message": (
                            "GitHub auth signal not corroborated by a live probe "
                            "— treating as a transient blip; not pausing."
                        ),
                        "source": loop_name,
                        # Benign: a transient blip was absorbed, nothing paused.
                        # Render yellow, not the red critical banner.
                        "severity": "warning",
                    },
                )
            )
            await self._restart_loop(
                loop_name,
                exc,
                tasks,
                loop_factories,
                restart_delay=_AUTH_TRANSIENT_RESTART_DELAY_S,
            )
            return

        logger.error(
            "GitHub authentication failed in %r — pausing all loops",
            loop_name,
        )
        self._auth_failed = True
        data: SystemAlertPayload = {
            "message": (
                "GitHub authentication failed. Check your gh token and restart."
            ),
            "source": loop_name,
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data=data,
            )
        )
        self._stop_event.set()

    async def _restart_loop(
        self,
        loop_name: str,
        exc: BaseException,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        restart_delay: float = 0.0,
    ) -> None:
        """Log, publish ERROR event, create a new loop task.

        ``restart_delay`` > 0 sleeps INSIDE the recreated task before the
        loop body starts (#9888 suppressed-credit backoff) — the supervisor
        is never blocked and the task stays tracked in the map.
        """
        if self._stop_event.is_set():
            # Shutdown has begun: recreating a loop task now would leak a live
            # task past ``_supervise_loops``'s cancel/gather drain, pinning
            # ``run_status`` at "stopping" forever (#10569). A restart exists
            # only to keep supervision alive, and supervision ends at stop.
            # The supervisor's finally sweeps the crashed task; no hot-loop.
            logger.debug(
                "Skipping restart of loop %r — stop already requested", loop_name
            )
            return
        logger.error("Loop %r crashed — restarting: %s", loop_name, exc)
        data: ErrorPayload = {
            "message": f"Loop {loop_name} crashed and was restarted",
            "source": loop_name,
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.ERROR,
                data=data,
            )
        )
        factory_fn = dict(loop_factories)[loop_name]

        async def _run_after_delay() -> None:
            if restart_delay > 0:
                await asyncio.sleep(restart_delay)
            await factory_fn()

        tasks[loop_name] = asyncio.create_task(
            _run_after_delay(), name=f"hydraflow-{loop_name}"
        )

    async def restart_loop_task(self, name: str) -> bool:
        """Cancel a (possibly silently-stalled) loop task and start a fresh one.

        The restart verb behind ``BGWorkerManager.restart`` — used by
        HealthMonitorLoop's restart-first stall policy. The supervisor only
        wakes on task *completion*, so a loop blocked forever on an ``await``
        is invisible to it; this cancels the wedged task and recreates it
        from the factory retained by :meth:`_supervise_loops`.

        The replacement is registered in ``self._loop_tasks`` *synchronously*
        after ``cancel()`` (no await between) so the supervisor's identity
        check sees old task and replacement atomically.

        Deliberately does NOT await the old task's drain: that await would
        deliver — and a suppress would swallow — the *caller's* own
        cancellation (e.g. the health-monitor work task being cancelled by
        a credit-pause shutdown), letting the staleness sweep escape its
        one cancel and spawn rogue loop tasks against an exhausted billing
        signal. The supervisor drains the cancelled old task through its
        done-set via the identity check; cancelled tasks emit no
        never-retrieved warnings.

        Returns ``False`` for unknown names or before supervision started.
        """
        if self._stop_event.is_set():
            # A restart requested after stop (e.g. HealthMonitorLoop's
            # restart-first stall policy racing a shutdown) would spawn a rogue
            # loop task that outlives ``_supervise_loops``'s drain and wedges
            # ``run_status`` at "stopping" (#10569). Refuse once stop is set.
            return False
        old = self._loop_tasks.get(name)
        factory = self._loop_factories.get(name)
        if old is None or factory is None:
            return False
        old.cancel()
        self._loop_tasks[name] = asyncio.create_task(
            factory(), name=f"hydraflow-{name}"
        )
        logger.info("Loop %r restarted via restart_loop_task", name)
        return True

    async def _handle_loop_exception(
        self,
        name: str,
        exc: BaseException,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Handle a crashed loop task — auth failure, credit exhaustion, or generic restart."""
        if isinstance(exc, AuthenticationError):
            await self._handle_auth_error(name, exc, tasks, loop_factories)
            return

        if isinstance(exc, CreditExhaustedError):
            await self._handle_credit_exhaustion(exc, name, tasks, loop_factories)
            return

        await self._restart_loop(name, exc, tasks, loop_factories)

"""Base class for background worker loops.

Extracts the shared run-loop, error handling, success reporting,
interval management, and enabled-check logic that was previously
duplicated across memory_sync_loop, metrics_sync_loop,
pr_unsticker_loop, and manifest_refresh_loop.

Loops are event-driven: each subclass declares which ``EventType``
signals trigger an immediate run via :meth:`_signal_types`.  A timer
fallback still fires at the configured interval so external changes
are eventually picked up.  A minimum cooldown (default 30 s) prevents
thrashing when many events arrive in a burst.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import StatusCallback
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.base_background_loop")

_DEFAULT_MIN_COOLDOWN: int = 30  # seconds


class BaseBackgroundLoop(abc.ABC):
    """Abstract base for background worker loops.

    Subclasses implement :meth:`_do_work` (domain-specific logic),
    :meth:`_get_default_interval` (config-driven default interval), and
    :meth:`_signal_types` (event types that trigger an immediate run).

    The run loop combines two wake-up sources:

    1. **Timer** — fires every ``_get_interval()`` seconds (fallback).
    2. **Signal listener** — wakes immediately when a matching event
       arrives on the ``EventBus``.

    A minimum cooldown (:attr:`_min_cooldown`) prevents runs from
    happening more frequently than every *N* seconds regardless of how
    many signals arrive.
    """

    def __init__(
        self,
        *,
        worker_name: str,
        config: HydraFlowConfig,
        bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
        run_on_startup: bool = False,
        min_cooldown: int = _DEFAULT_MIN_COOLDOWN,
    ) -> None:
        self._worker_name = worker_name
        self._config = config
        self._bus = bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn
        self._interval_cb = interval_cb
        self._run_on_startup = run_on_startup
        self._min_cooldown = min_cooldown

        # Signal trigger — set by the signal-listener task to wake the
        # main loop early.
        self._trigger_event: asyncio.Event = asyncio.Event()
        # Monotonic timestamp of the last completed work cycle (used for
        # cooldown enforcement).
        self._last_run_mono: float = 0.0

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def _do_work(self) -> dict[str, Any] | None:
        """Execute one cycle of domain-specific work.

        Returns an optional stats/details dict to include in the
        BACKGROUND_WORKER_STATUS event.
        """

    @abc.abstractmethod
    def _get_default_interval(self) -> int:
        """Return the config-driven default interval in seconds."""

    def _signal_types(self) -> frozenset[EventType]:
        """Return event types that should trigger an immediate run.

        Subclasses override this to declare their triggers.  The default
        returns an empty set (pure timer-based, backward-compatible).
        """
        return frozenset()

    # ------------------------------------------------------------------
    # Interval / cooldown helpers
    # ------------------------------------------------------------------

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb(self._worker_name)
        return self._get_default_interval()

    def _seconds_until_cooldown_expires(self) -> float:
        """Seconds remaining before the cooldown window expires (>= 0)."""
        elapsed = time.monotonic() - self._last_run_mono
        return max(0.0, self._min_cooldown - elapsed)

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def _trigger(self) -> None:
        """Wake the main loop so it runs a cycle as soon as cooldown allows."""
        self._trigger_event.set()

    # ------------------------------------------------------------------
    # Signal listener
    # ------------------------------------------------------------------

    async def _signal_listener(self) -> None:
        """Subscribe to the EventBus and set the trigger on matching events."""
        signals = self._signal_types()
        if not signals:
            return  # No signals declared — nothing to listen to.

        queue = self._bus.subscribe()
        try:
            while not self._stop_event.is_set():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                if event.type in signals:
                    logger.debug(
                        "%s triggered by %s event",
                        self._worker_name,
                        event.type,
                    )
                    self._trigger()
        finally:
            self._bus.unsubscribe(queue)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_details(self, stats: dict[str, Any] | None) -> dict[str, Any]:
        """Coerce arbitrary worker stats into a details dict."""
        if stats is None:
            return {}
        if isinstance(stats, dict):
            return dict(stats)
        return {"value": stats}

    async def _execute_cycle(self) -> None:
        """Execute one work cycle with error handling and status reporting."""
        try:
            stats = await self._do_work()
            details = self._build_details(stats)
            last_run = datetime.now(UTC).isoformat()
            self._status_cb(self._worker_name, "ok", details)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": self._worker_name,
                        "status": "ok",
                        "last_run": last_run,
                        "details": details,
                    },
                )
            )
        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception:
            logger.exception(
                "%s loop iteration failed — will retry next cycle",
                self._worker_name.replace("_", " ").capitalize(),
            )
            last_run = datetime.now(UTC).isoformat()
            self._status_cb(self._worker_name, "error", {})
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": self._worker_name,
                        "status": "error",
                        "last_run": last_run,
                        "details": {},
                    },
                )
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.ERROR,
                    data={
                        "message": f"{self._worker_name.replace('_', ' ').capitalize()} loop error",
                        "source": self._worker_name,
                    },
                )
            )
        finally:
            self._last_run_mono = time.monotonic()

    # ------------------------------------------------------------------
    # Interruptible sleep
    # ------------------------------------------------------------------

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep for *seconds*, but return early if a signal triggers.

        Uses ``_sleep_fn`` as the timer so tests can inject an instant
        sleep that also controls the stop event.  Also wakes immediately
        when the stop event or trigger event is set.

        Returns ``True`` if a signal woke us, ``False`` if the full
        duration elapsed or the stop event was set.
        """
        self._trigger_event.clear()

        stop_task = asyncio.create_task(self._stop_event.wait())
        trigger_task = asyncio.create_task(self._trigger_event.wait())
        sleep_task = asyncio.create_task(self._sleep_fn(seconds))

        try:
            done, pending = await asyncio.wait(
                {stop_task, trigger_task, sleep_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            return trigger_task in done
        except asyncio.CancelledError:
            stop_task.cancel()
            trigger_task.cancel()
            sleep_task.cancel()
            raise

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the background worker loop until the stop event is set.

        A signal-listener task runs alongside the main loop.  When a
        matching event arrives the remaining sleep is interrupted and
        the cycle runs immediately (subject to cooldown).
        """
        listener_task: asyncio.Task[None] | None = None
        if self._signal_types():
            listener_task = asyncio.create_task(
                self._signal_listener(),
                name=f"{self._worker_name}-signal-listener",
            )

        try:
            if self._run_on_startup:
                await self._execute_cycle()

            while not self._stop_event.is_set():
                interval = self._get_interval()

                # --- sleep phase (interruptible) ---
                triggered = await self._interruptible_sleep(interval)

                if self._stop_event.is_set():
                    break

                if not self._enabled_cb(self._worker_name):
                    continue

                # --- cooldown enforcement ---
                if triggered:
                    remaining = self._seconds_until_cooldown_expires()
                    if remaining > 0:
                        logger.debug(
                            "%s signal received but cooldown has %.1fs remaining",
                            self._worker_name,
                            remaining,
                        )
                        await self._interruptible_sleep(remaining)
                        if self._stop_event.is_set():
                            break
                        if not self._enabled_cb(self._worker_name):
                            continue

                # Clear any pending trigger before executing so we don't
                # immediately re-trigger after the cycle completes.
                self._trigger_event.clear()

                await self._execute_cycle()
        finally:
            if listener_task is not None:
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

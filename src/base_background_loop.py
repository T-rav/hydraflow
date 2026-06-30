"""Base class for background worker loops.

Extracts the shared run-loop, error handling, success reporting,
interval management, and enabled-check logic that was previously
duplicated across memory_sync_loop and pr_unsticker_loop.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness
from models import (
    BackgroundWorkerStatusPayload,
    ErrorPayload,
    StatusCallback,
    WorkCycleResult,  # noqa: TCH002
)
from runner_utils import AuthenticationRetryError
from subprocess_util import AuthenticationError, CreditExhaustedError
from telemetry.spans import loop_span  # noqa: E402

logger = logging.getLogger("hydraflow.base_background_loop")


class LoopCycleTimeoutError(Exception):
    """Raised when a loop's ``_do_work()`` cycle exceeds its watchdog bound.

    The per-loop watchdog (#9455 / #9556) bounds every cycle so a hung loop —
    a wedged subprocess, a deadlocked ``await``, an unbounded network wait —
    cannot block indefinitely and silently freeze its heartbeat. Carries the
    worker name and the bound that was exceeded for diagnosis. Surfaced as a
    cycle error (status ``error`` + ERROR event); the loop survives and retries
    on the next tick rather than crashing.
    """

    def __init__(self, worker_name: str, timeout_seconds: float) -> None:
        self.worker_name = worker_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"{worker_name} work cycle exceeded its {timeout_seconds:g}s "
            "watchdog bound and was cancelled"
        )


def _make_sleep_fn(
    stop_event: asyncio.Event,
) -> Callable[[int | float], Coroutine[Any, Any, None]]:
    """Create a sleep function that wakes early when *stop_event* is set."""

    async def _sleep_or_stop(seconds: int | float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=seconds)

    return _sleep_or_stop


@dataclass(frozen=True)
class LoopDeps:
    """Shared dependencies passed to every background loop.

    Bundles the parameters that are identical across all
    :class:`BaseBackgroundLoop` subclasses so that callers pass a single
    object instead of repeating six keyword arguments.
    """

    event_bus: EventBus
    stop_event: asyncio.Event
    status_cb: StatusCallback
    enabled_cb: Callable[[str], bool]
    sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]] | None = None
    interval_cb: Callable[[str], int] | None = None
    # Resolves the per-loop work-cycle watchdog bound (seconds) by worker name.
    # Optional + forward-compatible: when None the loop derives its bound from
    # config (LONG_LLM_CYCLE → loop_watchdog_llm_seconds, else
    # loop_watchdog_default_seconds). Mirrors ``interval_cb`` (#9556).
    timeout_cb: Callable[[str], int] | None = None


class BaseBackgroundLoop(abc.ABC):
    """Abstract base for background worker loops.

    Subclasses implement :meth:`_do_work` (domain-specific logic) and
    :meth:`_get_default_interval` (config-driven default interval).
    The base class handles the run loop, enabled check, error reporting,
    status publishing, and interval management.
    """

    # Loops that call an LLM (run_lightweight_agent et al.) set this True to
    # earn the longer ``loop_watchdog_llm_seconds`` cycle bound instead of the
    # short ``loop_watchdog_default_seconds`` one (#9455 / #9556). Default False
    # keeps every non-LLM loop on the tight bound.
    LONG_LLM_CYCLE: ClassVar[bool] = False

    def __init__(
        self,
        *,
        worker_name: str,
        config: HydraFlowConfig,
        deps: LoopDeps,
        run_on_startup: bool = False,
    ) -> None:
        self._worker_name = worker_name
        self._config = config
        self._bus = deps.event_bus
        self._stop_event = deps.stop_event
        self._status_cb = deps.status_cb
        self._enabled_cb = deps.enabled_cb
        self._sleep_fn = (
            deps.sleep_fn
            if deps.sleep_fn is not None
            else _make_sleep_fn(deps.stop_event)
        )
        self._interval_cb = deps.interval_cb
        self._timeout_cb = deps.timeout_cb
        self._run_on_startup = run_on_startup
        self._trigger_event = asyncio.Event()

    @property
    def name(self) -> str:
        """Loop name used by loop_span() for span naming and hf.loop attribute."""
        return self._worker_name

    @abc.abstractmethod
    async def _do_work(self) -> WorkCycleResult:
        """Execute one cycle of domain-specific work.

        Returns an optional stats/details dict to include in the
        BACKGROUND_WORKER_STATUS event.
        """

    @abc.abstractmethod
    def _get_default_interval(self) -> int:
        """Return the config-driven default interval in seconds."""

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        """Return this loop's fitness for the window in ``ctx``.

        Default is HOUSEKEEPING (no normalized score). Loops with a meaningful
        objective override this to return SCORED fitness. Must be PURE over
        ``ctx`` — no network, no clock, no mutable ``self`` state — so the same
        function can score replayed history for the deferred optimizer.
        ``tests/test_loop_fitness_completeness.py`` forces every new loop to
        override this.
        """
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            components={},
            sample_count=0,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    def trigger(self) -> None:
        """Request an immediate execution of the next work cycle.

        Interrupts the current sleep so the loop runs without waiting
        for the full polling interval to elapse.
        """
        self._trigger_event.set()

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb(self._worker_name)
        return self._get_default_interval()

    def _cycle_timeout_seconds(self) -> int:
        """Resolve this loop's per-cycle watchdog bound in seconds (#9556).

        Prefers the injected ``timeout_cb`` (operator-tunable, per-loop); else
        derives from config: :attr:`LONG_LLM_CYCLE` loops get the longer
        ``loop_watchdog_llm_seconds`` bound, all others the tight
        ``loop_watchdog_default_seconds`` one.
        """
        if self._timeout_cb is not None:
            return self._timeout_cb(self._worker_name)
        if self.LONG_LLM_CYCLE:
            return self._config.loop_watchdog_llm_seconds
        return self._config.loop_watchdog_default_seconds

    def _build_details(self, stats: dict[str, Any] | None) -> dict[str, Any]:
        """Coerce arbitrary worker stats into a details dict."""
        if stats is None:
            return {}
        if isinstance(stats, dict):
            return dict(stats)
        return {"value": stats}

    @loop_span()
    async def _execute_cycle(self) -> None:
        """Execute one work cycle with error handling and status reporting.

        The ``_do_work()`` call is bounded by a per-loop watchdog
        (:meth:`_cycle_timeout_seconds`): if a cycle overruns its timeout the
        work task is cancelled and :class:`LoopCycleTimeoutError` is raised, so
        a hung loop surfaces as a cycle error and retries next tick instead of
        freezing its heartbeat forever (#9455 / #9556).
        """
        timeout = self._cycle_timeout_seconds()
        work_task = asyncio.create_task(self._do_work())
        try:
            done, _pending = await asyncio.wait({work_task}, timeout=timeout)
            if work_task not in done:
                raise LoopCycleTimeoutError(self._worker_name, timeout)
            stats = work_task.result()
            details = self._build_details(stats)
            last_run = datetime.now(UTC).isoformat()
            self._status_cb(self._worker_name, "ok", details)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data=BackgroundWorkerStatusPayload(
                        worker=self._worker_name,
                        status="ok",
                        last_run=last_run,
                        details=details,
                    ),
                )
            )
        except (AuthenticationError, CreditExhaustedError):
            raise
        except AuthenticationRetryError:
            raise
        except LoopCycleTimeoutError as exc:
            # Watchdog fired: the cycle overran its bound. Surface it as a
            # distinct WARNING (not a bug traceback) plus an error status, so a
            # hung loop is visible in the dashboard / Sentry without
            # masquerading as a code fault (#9556).
            logger.warning("%s", exc)
            await self._report_cycle_failure(
                f"{self._worker_name.replace('_', ' ').capitalize()} loop "
                "watchdog timeout"
            )
        except Exception:
            logger.exception(
                "%s loop iteration failed — will retry next cycle",
                self._worker_name.replace("_", " ").capitalize(),
            )
            await self._report_cycle_failure(
                f"{self._worker_name.replace('_', ' ').capitalize()} loop error"
            )
        finally:
            # Never let the work task outlive the cycle. On a watchdog timeout —
            # or if _execute_cycle itself is cancelled (loop shutdown) while
            # awaiting — an un-drained task orphans and blocks event-loop
            # teardown's _cancel_all_tasks gather. Cancel + drain it here so the
            # cycle owns its task's full lifecycle.
            if not work_task.done():
                work_task.cancel()
                with contextlib.suppress(BaseException):
                    await work_task

    async def _report_cycle_failure(self, message: str) -> None:
        """Publish the error status + ERROR event for a failed/timed-out cycle."""
        last_run = datetime.now(UTC).isoformat()
        self._status_cb(self._worker_name, "error", {})
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data=BackgroundWorkerStatusPayload(
                    worker=self._worker_name,
                    status="error",
                    last_run=last_run,
                    details={},
                ),
            )
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.ERROR,
                data=ErrorPayload(message=message, source=self._worker_name),
            )
        )

    async def _sleep_or_trigger(self, seconds: int | float) -> bool:
        """Call the configured sleep function, but return early on trigger.

        Races ``_sleep_fn(seconds)`` against the trigger event so that
        :meth:`trigger` can interrupt any pending sleep.  Returns ``True``
        if the sleep was cut short by a trigger, ``False`` if it ran to
        completion.

        If the trigger event is already set when this method is called
        (i.e. :meth:`trigger` was called during the preceding work cycle),
        the sleep is skipped entirely and ``True`` is returned immediately.
        """
        if self._trigger_event.is_set():
            self._trigger_event.clear()
            return True
        sleep_task = asyncio.create_task(self._sleep_fn(seconds))
        trigger_task = asyncio.create_task(self._trigger_event.wait())
        try:
            done, pending = await asyncio.wait(
                {sleep_task, trigger_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
            triggered = trigger_task in done
            if triggered:
                self._trigger_event.clear()
            return triggered
        except BaseException:
            sleep_task.cancel()
            trigger_task.cancel()
            raise

    def _should_run_catchup(self) -> bool:
        """Return True if a cycle was missed while the system was down.

        Checks the persisted ``last_run`` timestamp from the status
        callback's backing store (``state.json``).  If ``now - last_run``
        exceeds the configured interval, the worker should run immediately
        on startup to catch up on missed work.
        """
        try:
            # The status_cb stores last_run via StateTracker.set_worker_heartbeat.
            # We can't read it back through the callback, so we check whether
            # run_on_startup is already True (which forces an immediate run)
            # or infer from the interval_cb / enabled state.
            # For a clean implementation, we use a file-based timestamp.
            ts_path = (
                self._config.data_root / "memory" / f".{self._worker_name}_last_run"
            )
            if not ts_path.exists():
                return False
            last_run_str = ts_path.read_text().strip()
            if not last_run_str:
                return False
            last_run = datetime.fromisoformat(last_run_str)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=UTC)
            elapsed = (datetime.now(UTC) - last_run).total_seconds()
            return elapsed > self._get_interval()
        except Exception:  # noqa: BLE001
            logger.debug(
                "%s: catchup timestamp read failed", self._worker_name, exc_info=True
            )
            return False

    def _record_last_run(self) -> None:
        """Persist the current timestamp for missed-cycle detection on restart."""
        try:
            ts_path = (
                self._config.data_root / "memory" / f".{self._worker_name}_last_run"
            )
            ts_path.parent.mkdir(parents=True, exist_ok=True)
            ts_path.write_text(datetime.now(UTC).isoformat())
        except Exception:  # noqa: BLE001
            # best-effort — don't break the loop, but leave a breadcrumb
            logger.debug("%s: timestamp write failed", self._worker_name, exc_info=True)

    async def run(self) -> None:
        """Run the background worker loop until the stop event is set."""
        # Run immediately if configured, or if cycles were missed during downtime
        if self._run_on_startup or self._should_run_catchup():
            try:
                await self._execute_cycle()
            except AuthenticationRetryError:
                logger.warning(
                    "%s startup cycle hit transient auth error — will retry next cycle",
                    self._worker_name.replace("_", " ").capitalize(),
                )
            self._record_last_run()

        while not self._stop_event.is_set():
            interval = self._get_interval()
            if self._run_on_startup:
                triggered = await self._sleep_or_trigger(interval)
                if self._stop_event.is_set():
                    break
                if not self._enabled_cb(self._worker_name) and not triggered:
                    continue
            elif not self._enabled_cb(self._worker_name):
                triggered = await self._sleep_or_trigger(interval)
                if not triggered:
                    continue
            try:
                await self._execute_cycle()
            except AuthenticationRetryError:
                logger.warning(
                    "%s hit transient auth error — will retry next cycle",
                    self._worker_name.replace("_", " ").capitalize(),
                )
            self._record_last_run()
            if not self._run_on_startup:
                await self._sleep_or_trigger(interval)

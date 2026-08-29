"""The polling loops of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorLoopsMixin`.

One cohesive concern: the ADR-0001 "check enabled -> try work -> except ->
sleep" shape and the thin per-stage loops built on it. ``_polling_loop`` is
moved byte-for-byte, including the #11641 fix that stops an IDLE
``DriverTickReport.did_work`` from skipping the sleep — nothing in this
control flow was restructured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from models import ErrorPayload, SystemAlertPayload, WorkFn
from phase_utils import (
    INFRA_FATAL_EXCEPTIONS,
    is_likely_bug,
    log_exception_with_bug_classification,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from hitl_controller import HITLController
    from service_registry import ServiceRegistry
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorLoopsMixin:
    """The polling loops of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _hitl_ctrl: HITLController
    _pipeline_enabled: bool
    _state: StateTracker
    _stop_event: asyncio.Event
    _svc: ServiceRegistry

    #: One-shot latch for the "no pipeline target" warning. A real class-level
    #: DEFAULT, not a TYPE_CHECKING seam stub — the mixin has no ``__init__`` to
    #: hook, and first assignment shadows this with an instance attribute. A
    #: stub spelled ``...`` here would win the MRO at runtime and be truthy,
    #: which would suppress the warning entirely.
    _warned_no_pipeline_target: bool = False

    if TYPE_CHECKING:

        async def _apply_human_steering(
            self,
        ) -> None: ...  # provided by OrchestratorHITLMixin

        async def _do_implement_work(
            self,
        ) -> bool: ...  # provided by OrchestratorWorkMixin

        async def _do_review_work(
            self,
        ) -> bool: ...  # provided by OrchestratorWorkMixin

        def is_bg_worker_enabled(
            self, name: str
        ) -> bool: ...  # provided by OrchestratorBGWorkersMixin

        def update_bg_worker_status(
            self, name: str, status: str, details: dict[str, Any] | None = None
        ) -> None: ...  # provided by OrchestratorBGWorkersMixin

    def _is_slug_blocked(self, slug: str) -> bool:
        """Return True if this repo slug is blocked by onboarding gate (§4.4)."""
        return slug in self._state.blocked_slugs()

    async def _pipeline_work_wrapper(
        self,
        slug: str,
        inner: Callable[[], Coroutine[Any, Any, Any]],
    ) -> object:
        """Skip this cycle if slug is onboarding-blocked (§4.4).

        Returns ``False`` (falsy, so ``_polling_loop`` sleeps) when the slug is
        blocked; otherwise passes through the inner callable's return value —
        pipeline work functions have heterogeneous return types (``bool``,
        ``int``, ``list[PlanResult]``) but ``_polling_loop`` only inspects
        truthiness via ``bool(await work_fn())``.
        """
        if not slug:
            # No pipeline target. Every pipeline loop funnels through here, so
            # one guard idles all five rather than each polling GitHub with an
            # empty slug. Warn ONCE — this is a steady state an operator chose,
            # not an error, and repeating it every poll_interval would bury the
            # log it is meant to be visible in.
            if not self._warned_no_pipeline_target:
                self._warned_no_pipeline_target = True
                logger.warning(
                    "Pipeline loops idle: no target repo. The factory does NOT "
                    "adopt the checkout it runs from — set HYDRAFLOW_GITHUB_REPO"
                    "=<owner>/<repo> (or config.repo) to give it work."
                )
            return False
        if self._is_slug_blocked(slug):
            logger.debug("Skipping %s — onboarding blocked", slug)
            return False
        return await inner()

    async def _polling_loop(
        self,
        name: str,
        work_fn: WorkFn,
        interval: int,
        enabled_name: str | None = None,
        max_consecutive_failures: int = 5,
        is_pipeline: bool = False,
    ) -> None:
        """Generic polling loop: check enabled -> try work -> except -> sleep.

        Tracks consecutive failures by exception type.  After
        *max_consecutive_failures* of the **same** type in a row the loop
        escalates with a ``SYSTEM_ALERT`` event so operators can detect
        permanent failure loops (e.g. a code bug being silently retried).
        """
        consecutive_failures = 0
        last_exc_type: type[BaseException] | None = None

        while not self._stop_event.is_set():
            if is_pipeline and not self._pipeline_enabled:
                await self._sleep_or_stop(interval)
                continue
            if enabled_name is not None and not self.is_bg_worker_enabled(enabled_name):
                await self._sleep_or_stop(interval)
                continue
            try:
                did_work = bool(await work_fn())
            except INFRA_FATAL_EXCEPTIONS:
                raise
            except Exception as exc:
                display = name.replace("_", " ").capitalize()
                exc_type = type(exc)

                # Docker/network transient errors should not count toward
                # the circuit breaker — they resolve on their own when the
                # daemon restarts or the network recovers.
                is_transient = (
                    isinstance(exc, ConnectionError | FileNotFoundError | OSError)
                    or "closed pipe" in str(exc).lower()
                )

                # Track consecutive failures of the same type
                if is_transient:
                    # Don't escalate transient infra errors
                    consecutive_failures = 0
                    last_exc_type = None
                elif exc_type is last_exc_type:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 1
                    last_exc_type = exc_type

                # Classify for event bus data; severity handled inside helper
                exc_is_bug = is_likely_bug(exc)
                log_exception_with_bug_classification(
                    logger,
                    exc,
                    f"{display} loop iteration failed — will retry next cycle",
                )

                error_data: ErrorPayload = {
                    "message": f"{display} loop error",
                    "source": name,
                    "exception_type": exc_type.__name__,
                    "is_likely_bug": exc_is_bug,
                    "consecutive_failures": consecutive_failures,
                }
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.ERROR,
                        data=error_data,
                    )
                )

                # Circuit breaker: escalate exactly once when threshold is crossed
                if consecutive_failures == max_consecutive_failures:
                    logger.critical(
                        "%s loop has failed %d consecutive times with %s "
                        "— escalating via SYSTEM_ALERT",
                        display,
                        consecutive_failures,
                        exc_type.__name__,
                    )
                    data: SystemAlertPayload = {
                        "message": (
                            f"{display} loop circuit breaker: "
                            f"{consecutive_failures} consecutive "
                            f"{exc_type.__name__} failures"
                        ),
                        "source": name,
                        "exception_type": exc_type.__name__,
                        "consecutive_failures": consecutive_failures,
                    }
                    await self._bus.publish(
                        HydraFlowEvent(
                            type=EventType.SYSTEM_ALERT,
                            data=data,
                        )
                    )

                self.update_bg_worker_status(name, "error")
                await self._sleep_or_stop(interval)
                continue
            else:
                # Success resets the failure counter
                consecutive_failures = 0
                last_exc_type = None
            self.update_bg_worker_status(name, "ok")
            if did_work:
                continue
            await self._sleep_or_stop(interval)

    async def _triage_loop(self) -> None:
        """Continuously poll for find-labeled issues and triage them."""
        # Operational kill-switch. Triage runs a full agent per issue; a bad
        # batch (e.g. un-triageable findings) can drive repeated infra errors.
        # The retry storm is now bounded (infra errors park — see
        # TriagePhase._triage_single_traced), but this switch lets an operator
        # hold triage off entirely without stopping the rest of the factory.
        # Idle on shutdown rather than returning — a bare return makes the loop
        # supervisor treat it as "completed unexpectedly" and hot-restart it.
        if os.environ.get("HYDRAFLOW_TRIAGE_DISABLED") == "1":
            logger.warning(
                "triage loop DISABLED via HYDRAFLOW_TRIAGE_DISABLED — no issues "
                "will be triaged until it is unset"
            )
            await self._stop_event.wait()
            return

        async def _work() -> object:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._svc.triager.triage_issues
            )

        await self._polling_loop(
            "triage",
            _work,
            self._config.poll_interval,
            enabled_name="triage",
            is_pipeline=True,
        )

    async def _plan_loop(self) -> None:
        """Continuously poll for planner-labeled issues."""

        async def _work() -> object:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._svc.planner_phase.plan_issues
            )

        await self._polling_loop(
            "plan",
            _work,
            self._config.poll_interval,
            enabled_name="plan",
            is_pipeline=True,
        )

    async def _implement_loop(self) -> None:
        """Continuously poll for ``hydraflow-ready`` issues and implement them."""

        async def _work() -> object:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._do_implement_work
            )

        await self._polling_loop(
            "implement",
            _work,
            self._config.poll_interval,
            enabled_name="implement",
            is_pipeline=True,
        )

    async def _review_loop(self) -> None:
        """Continuously consume reviewable issues from the store and review their PRs."""

        async def _work() -> object:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._do_review_work
            )

        await self._polling_loop(
            "review",
            _work,
            self._config.poll_interval,
            enabled_name="review",
            is_pipeline=True,
        )

    async def _hitl_loop(self) -> None:
        """Continuously process HITL corrections submitted via the dashboard."""

        async def _work() -> object:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._hitl_ctrl.do_work
            )

        await self._polling_loop(
            "hitl",
            _work,
            self._config.poll_interval,
            is_pipeline=True,
        )

    async def _issue_driver_loop(self) -> None:
        """Tick the ``issue_controller`` allocator (#11535, ADR-0137).

        Registered *instead of* the plan/implement/review/HITL loops, never
        alongside them, so exactly one consumer owns each stage queue. Runs
        only when ``scheduling_model=issue_controller``; under Classic this
        coroutine is never scheduled because the loop is not registered.
        """
        manager = self._svc.driver_manager
        if manager is None:  # pragma: no cover — not registered under Classic
            await self._stop_event.wait()
            return

        # #11537: a shadow director proves its runtime boundary before the loop
        # starts, and refuses rather than degrades (ADR-0137 S1/S4). The refusal
        # is scoped to the director: the deterministic controller is unaffected
        # and keeps running the pipeline, which is exactly the shadow-mode
        # contract — an observer that cannot observe must not take the factory
        # with it, and must not be believed to be observing either.
        director = self._svc.fable_director
        if director is not None:
            try:
                await director.preflight()
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.error(
                    "issue_driver: the Fable director could not prove its runtime "
                    "boundary and is DETACHED for this run; the deterministic "
                    "controller continues unchanged: %s",
                    exc,
                )
                manager.detach_observer()

        async def _work() -> object:
            report = await manager.tick(stop_requested=self._stop_event.is_set())
            return report.did_work

        await self._polling_loop(
            "issue_driver",
            _work,
            self._config.poll_interval,
            enabled_name="issue_driver",
            is_pipeline=True,
        )

    async def _human_steering_actuator_loop(self) -> None:
        """Continuously enact pending steering directives (ADR-0099 #4).

        Runs as its own single-task polling loop — not folded into the
        6 phase loops' shared ``_pipeline_work_wrapper`` — so pause/abort/redo
        decisions for a given issue are enacted from exactly one coroutine at
        a time. The phase loops themselves are unaware of steering; they
        simply won't see a paused/parked/re-enqueued issue reappear until the
        next phase-poll after this loop acts. No-op when
        ``human_steering_enabled`` is off (checked inside ``_apply_human_steering``).
        """

        async def _work() -> object:
            await self._apply_human_steering()
            return False  # never "did work" — always sleep the full interval

        await self._polling_loop(
            "human_steering_actuator",
            _work,
            self._config.human_steering_interval_seconds,
            is_pipeline=True,
        )

    async def _sleep_or_stop(self, seconds: int | float) -> None:
        """Sleep for *seconds*, waking early if stop is requested."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

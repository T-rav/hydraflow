"""Background-worker control surface of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorBGWorkersMixin`.

One cohesive concern: the thin façade over ``BGWorkerManager`` that the
dashboard drives — enable/disable, interval and watchdog-timeout overrides,
manual trigger, status heartbeats, and the boot-time seeding that publishes
one status event per registered ``BaseBackgroundLoop``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from models import BackgroundWorkerState, BackgroundWorkerStatusPayload

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from events import EventBus

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorBGWorkersMixin:
    """Background-worker control surface of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _bg_workers: BGWorkerManager
    _bus: EventBus

    def update_bg_worker_status(
        self, name: str, status: str, details: dict[str, Any] | None = None
    ) -> None:
        """Record the latest heartbeat from a background worker."""
        self._bg_workers.update_status(name, status, details)

    def set_bg_worker_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a background worker by name and persist to state."""
        self._bg_workers.set_enabled(name, enabled)

    def is_bg_worker_enabled(self, name: str) -> bool:
        """Return whether a background worker is enabled (defaults to True)."""
        return self._bg_workers.is_enabled(name)

    def get_bg_worker_states(self) -> dict[str, BackgroundWorkerState]:
        """Return a copy of all background worker states with enabled flag."""
        return self._bg_workers.get_states()

    def registered_bg_loop_names(self) -> set[str]:
        """Names of workers backed by a registered ``BaseBackgroundLoop``.

        Public passthrough for the System-tab route layer (#9503) — the
        watchdog-timeout knob is only meaningful for loop-backed workers
        (pipeline phases and other non-loop workers have no watchdog cycle).
        """
        return self._bg_workers.registered_loop_names()

    def trigger_bg_worker(self, name: str) -> bool:
        """Trigger an immediate execution of a background worker.

        Returns ``True`` if the worker was found and triggered, ``False``
        if *name* does not correspond to a registered ``BaseBackgroundLoop``.
        """
        return self._bg_workers.trigger(name)

    def set_bg_worker_interval(self, name: str, seconds: int) -> None:
        """Set a dynamic interval override for a background worker."""
        self._bg_workers.set_interval(name, seconds)

    def get_bg_worker_interval(self, name: str) -> int:
        """Return the effective interval for a background worker.

        Returns the dynamic override if set, otherwise the config default.
        """
        return self._bg_workers.get_interval(name)

    def set_bg_worker_timeout(self, name: str, seconds: int) -> None:
        """Set a dynamic watchdog-timeout override for a background worker (#9503)."""
        self._bg_workers.set_timeout(name, seconds)

    def get_bg_worker_timeout(self, name: str) -> int:
        """Return the effective per-cycle watchdog bound for a background worker.

        Returns the dynamic override if set, otherwise the loop's own
        (LONG_LLM_CYCLE-aware) config default. Mirrors
        :meth:`get_bg_worker_interval` (#9503).
        """
        return self._bg_workers.get_timeout(name)

    async def _seed_background_worker_statuses(self) -> None:
        """Publish an initial status for every registered background loop at boot.

        The operator console derives its loop-health count from the reducer's
        sticky ``backgroundWorkers`` slice, which accumulates
        ``BACKGROUND_WORKER_STATUS`` events by worker name and never evicts.
        Without a boot seed that slice only fills as loops tick, so slow loops
        (pricing-refresh, wiki-maint, RC-promotion — hours-long intervals) are
        absent for a long time and the count reads a partial set that climbs as
        loops report and shrinks again as a bounded event window ages them out
        (the 55→33 fluctuation, #10556).

        Seeding one event per *registered* loop (``bg_loop_registry``, the set
        of ``BaseBackgroundLoop`` instances — pipeline phases and other non-loop
        workers are intentionally excluded) makes the count the loop registry:
        accurate and stable from boot. A loop with a restored heartbeat keeps
        its real last status; a never-run loop reports ``pending`` (or
        ``disabled`` when its enabled flag is off) so it is counted but not
        mistaken for a healthy tick.

        Every seeded event carries ``seeded=True``. A restored ``error`` status
        is a genuine prior-session failure and must count toward loop-health,
        but it is NOT a live cycle — replaying it must not inflate the operator
        console's restart window. The flag lets the restart tally exclude seed
        replays while loop-health still reflects each loop's current status
        (#10751).
        """
        states = self._bg_workers.get_states()
        for name in sorted(self._bg_workers.registered_loop_names()):
            enabled = self._bg_workers.is_enabled(name)
            restored = states.get(name)
            if not enabled:
                status = "disabled"
                last_run = (restored or {}).get("last_run") or ""
                details = dict((restored or {}).get("details") or {})
            elif restored is not None:
                status = restored.get("status") or "pending"
                last_run = restored.get("last_run") or ""
                details = dict(restored.get("details") or {})
            else:
                status = "pending"
                last_run = ""
                details = {}
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data=BackgroundWorkerStatusPayload(
                        worker=name,
                        status=status,
                        last_run=last_run,
                        details=details,
                        enabled=enabled,
                        seeded=True,
                    ),
                )
            )

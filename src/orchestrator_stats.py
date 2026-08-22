"""Status and pipeline-stats reporting for :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorStatsMixin`.

One cohesive concern: what the factory *says about itself*. The lifecycle
``run_status`` string, the orchestrator status broadcast, the ADR-0014
``PipelineStats`` snapshot (including the session-counter forward-progression
map), and the ``pipeline_poller`` worker that emits it each cycle.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from events import EventType, HydraFlowEvent
from models import (
    OrchestratorStatusPayload,
    Phase,
    PipelineStats,
    StageStats,
    ThroughputStats,
)
from phase_utils import is_likely_bug

if TYPE_CHECKING:
    import asyncio
    from typing import Any

    from config import HydraFlowConfig
    from events import EventBus
    from issue_store import IssueStore
    from models import SessionLog
    from service_registry import ServiceRegistry
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorStatsMixin:
    """Status and pipeline-stats reporting for :class:`orchestrator.HydraFlowOrchestrator`."""

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
    _credits_paused_until: datetime | None
    _current_session: SessionLog | None
    _running: bool
    _state: StateTracker
    _stop_event: asyncio.Event
    _svc: ServiceRegistry

    if TYPE_CHECKING:

        def _has_active_processes(
            self,
        ) -> bool: ...  # provided by OrchestratorLifecycleMixin

        async def _sleep_or_stop(
            self, seconds: int | float
        ) -> None: ...  # provided by OrchestratorLoopsMixin

        @property
        def credits_paused_provider(
            self,
        ) -> str | None: ...  # provided by OrchestratorCreditsMixin

        @property
        def credits_paused_until(
            self,
        ) -> datetime | None: ...  # provided by OrchestratorCreditsMixin

        def get_bg_worker_interval(
            self, name: str
        ) -> int: ...  # provided by OrchestratorBGWorkersMixin

        def is_bg_worker_enabled(
            self, name: str
        ) -> bool: ...  # provided by OrchestratorBGWorkersMixin

        def update_bg_worker_status(
            self, name: str, status: str, details: dict[str, Any] | None = None
        ) -> None: ...  # provided by OrchestratorBGWorkersMixin

    @property
    def run_status(self) -> str:
        """Return the current lifecycle status: idle, running, stopping, auth_failed, credits_paused, or done."""
        if self._auth_failed:
            return "auth_failed"
        if (
            self._credits_paused_until is not None
            and self._credits_paused_until > datetime.now(UTC)
        ):
            return "credits_paused"
        if self._stop_event.is_set() and (
            self._running or self._has_active_processes()
        ):
            return "stopping"
        if self._running:
            return "running"
        # Check if we finished naturally (DONE phase in history)
        for event in reversed(self._bus.get_history()):
            if (
                event.type == EventType.PHASE_CHANGE
                and event.data.get("phase") == Phase.DONE.value
            ):
                return "done"
        return "idle"

    async def _publish_status(self) -> None:
        """Broadcast the current orchestrator status to all subscribers."""
        data: OrchestratorStatusPayload = {"status": self.run_status}
        if self.credits_paused_until:
            data["credits_paused_until"] = self.credits_paused_until.isoformat()
            if self.credits_paused_provider is not None:
                data["credits_paused_provider"] = self.credits_paused_provider
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data=data,
            )
        )

    def build_pipeline_stats(self) -> PipelineStats:
        """Build a unified snapshot of the pipeline state."""
        # ``get_queue_stats`` is orchestrator-only — not on IssueStorePort.
        queue_stats = cast("IssueStore", self._svc.store).get_queue_stats()
        lifetime = self._state.get_lifetime_stats()

        # Compute uptime from session start
        uptime = 0.0
        if self._current_session and self._current_session.started_at:
            try:
                started = datetime.fromisoformat(self._current_session.started_at)
                uptime = (datetime.now(UTC) - started).total_seconds()
            except (ValueError, TypeError):
                pass

        # Map stage keys to config worker caps
        stage_caps: dict[str, int] = {
            "triage": self._config.max_triagers,
            "plan": self._config.max_planners,
            "implement": self._config.max_workers,
            "review": self._config.max_reviewers,
            "hitl": self._config.max_hitl_workers,
        }

        # Map stage keys to runner pools for active worker counts
        stage_runners: dict[str, int] = {
            "triage": self._svc.triage.active_count,
            "plan": self._svc.planners.active_count,
            "implement": self._svc.agents.active_count,
            "review": self._svc.reviewers.active_count,
            "hitl": self._svc.hitl_runner.active_count,
        }

        # Map IssueStore stage names to our stage keys
        store_stage_map: dict[str, str] = {
            "find": "triage",
            "plan": "plan",
            "ready": "implement",
            "review": "review",
            "hitl": "hitl",
        }

        # Session counters from persisted state
        session_counters = self._state.get_session_counters()
        session_counter_map: dict[str, str] = {
            "triage": "triaged",
            "plan": "planned",
            "implement": "implemented",
            "review": "reviewed",
            "hitl": "",  # HITL has no dedicated counter; shows 0
        }

        stages: dict[str, StageStats] = {}
        for stage_key in (
            "triage",
            "plan",
            "implement",
            "review",
            "hitl",
        ):
            # Find the IssueStore stage name for queue/active lookups
            store_key = next(
                (k for k, v in store_stage_map.items() if v == stage_key), stage_key
            )
            queued = queue_stats.queue_depth.get(store_key, 0)
            active = queue_stats.active_count.get(store_key, 0)
            counter_field = session_counter_map.get(stage_key, "")
            session_processed = (
                getattr(session_counters, counter_field, 0) if counter_field else 0
            )
            completed_lt = queue_stats.total_processed.get(store_key, 0)

            stages[stage_key] = StageStats(
                queued=queued,
                active=active,
                completed_session=session_processed,
                completed_lifetime=completed_lt,
                worker_count=stage_runners.get(stage_key, 0),
                worker_cap=stage_caps.get(stage_key),
            )

        # Add a merged pseudo-stage from session counters and lifetime stats
        stages["merged"] = StageStats(
            completed_session=session_counters.merged,
            completed_lifetime=lifetime.prs_merged,
        )

        # Compute throughput (issues/hour) from session counters / uptime
        session_throughput = self._state.compute_session_throughput()
        throughput = ThroughputStats(
            triage=session_throughput.get("triaged", 0.0),
            plan=session_throughput.get("planned", 0.0),
            implement=session_throughput.get("implemented", 0.0),
            review=session_throughput.get("reviewed", 0.0),
            hitl=0.0,
        )

        return PipelineStats(
            timestamp=datetime.now(UTC).isoformat(),
            stages=stages,
            queue=queue_stats,
            throughput=throughput,
            uptime_seconds=round(uptime, 1),
            # Failure-class split (#11593 seam 3): why implement attempts die,
            # counted by ImplementPhase at result classification.
            implement_failures=dict(session_counters.implement_failures),
        )

    async def emit_pipeline_stats(self) -> None:
        """Build and publish a PIPELINE_STATS event."""
        stats = self.build_pipeline_stats()
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.PIPELINE_STATS,
                data=stats.model_dump(),
            )
        )

    async def _pipeline_stats_loop(self) -> None:
        """Emit pipeline stats each cycle as the ``pipeline_poller`` worker.

        Honors the System-tab worker controls the same way the other
        background workers do: it skips a cycle when the worker is disabled,
        re-reads its interval each cycle so operator edits take effect without
        an orchestrator restart, and publishes a per-cycle heartbeat so the
        dashboard renders an ``ok``/``error`` status instead of a permanently
        stale row.
        """
        stats_failures = 0
        while not self._stop_event.is_set():
            if not self.is_bg_worker_enabled("pipeline_poller"):
                await self._sleep_or_stop(
                    self.get_bg_worker_interval("pipeline_poller")
                )
                continue
            interval = self.get_bg_worker_interval("pipeline_poller")
            try:
                await self.emit_pipeline_stats()
                stats_failures = 0
                self.update_bg_worker_status("pipeline_poller", "ok")
            except Exception as exc:
                stats_failures += 1
                self.update_bg_worker_status("pipeline_poller", "error")
                if is_likely_bug(exc) or stats_failures >= 5:
                    logger.critical(
                        "Pipeline stats emission failed (%s, %d consecutive)",
                        type(exc).__name__,
                        stats_failures,
                        exc_info=True,
                    )
                else:
                    logger.warning("Pipeline stats emission failed", exc_info=True)
            await self._sleep_or_stop(interval)

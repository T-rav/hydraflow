"""Process lifecycle of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin. ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorLifecycleMixin`, so the class keeps ONE identity in
``orchestrator`` and every ``orchestrator.HydraFlowOrchestrator.run`` /
``.stop`` / ``.reset`` call site resolves unchanged.

One cohesive concern: bringing the factory up and taking it back down —
deferred repo init, state restore, the session log open/close pair, the
cooperative ``stop`` that cancels loop tasks and reaps subprocesses, and the
``reset`` that makes a stopped orchestrator restartable. ``run`` itself stays
in ``orchestrator.py`` next to the supervisor it hands off to.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from events import EventType, HydraFlowEvent
from models import (
    SessionEndPayload,
    SessionLog,
    SessionStartPayload,
    SessionStatus,
    SystemAlertPayload,
)
from runner_utils import reap_all_tracked_processes

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from hitl_controller import HITLController
    from issue_store import IssueStore
    from pr_manager import PRManager
    from service_registry import ServiceRegistry
    from state import StateTracker
    from state_restorer import StateRestorer
    from workspace import WorkspaceManager

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorLifecycleMixin:
    """Process lifecycle of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _active_issues_lock: asyncio.Lock
    _auth_failed: bool
    _bus: EventBus
    _config: HydraFlowConfig
    _credit_paused_provider: str | None
    _credit_resume_event: asyncio.Event
    _credits_paused_until: datetime | None
    _current_session: SessionLog | None
    _failover_probe_task: asyncio.Task[None] | None
    _hitl_ctrl: HITLController
    _loop_tasks: dict[str, asyncio.Task[None]]
    _pipeline_enabled: bool
    _recovered_issues: set[int]
    _running: bool
    _session_issue_results: dict[int, bool]
    _state: StateTracker
    _state_restorer: StateRestorer
    _stop_event: asyncio.Event
    _svc: ServiceRegistry

    if TYPE_CHECKING:

        async def _publish_status(
            self,
        ) -> None: ...  # provided by OrchestratorStatsMixin

        def _sync_active_issue_numbers(
            self,
        ) -> None: ...  # provided by OrchestratorHITLMixin

    async def _deferred_pipeline_start(self) -> None:
        """Run repo initialization that was skipped when pipeline was disabled.

        On failure the pipeline toggle is reverted to ``False`` and a
        ``SYSTEM_ALERT`` is published so the dashboard can surface the error
        (#6360). Without this the pipeline would be left enabled with no
        session and no retry — a silently broken state.
        """
        try:
            # Concrete-only setup methods (sanitize_repo, ensure_labels_exist,
            # enable_rerere) are not on the Port — they are real-process
            # bootstrap operations that Fakes have no business implementing.
            workspaces: WorkspaceManager = cast(
                "WorkspaceManager", self._svc.workspaces
            )
            prs: PRManager = cast("PRManager", self._svc.prs)
            await workspaces.sanitize_repo()
            await prs.ensure_labels_exist()
            await workspaces.enable_rerere()
            self._warn_if_agents_md_missing()
            if self._current_session is None:
                await self._start_session()
            logger.info("Pipeline enabled — repo initialized and session started")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed deferred pipeline start")
            self._pipeline_enabled = False
            data: SystemAlertPayload = {
                "message": (
                    "Pipeline start failed during deferred repo "
                    f"initialization: {exc}. Pipeline has been disabled — "
                    "fix the underlying cause and re-enable."
                ),
                "source": "deferred_pipeline_start",
            }
            await self._bus.publish(
                HydraFlowEvent(type=EventType.SYSTEM_ALERT, data=data)
            )

    def _has_active_processes(self) -> bool:
        """Return True if any runner pool still has live subprocesses."""
        return bool(
            self._svc.planners.active_count
            or self._svc.agents.active_count
            or self._svc.reviewers.active_count
            or self._svc.hitl_runner.active_count
        )

    async def stop(self) -> None:
        """Signal the orchestrator to stop and kill active subprocesses.

        Checkpoints interrupted issues before cancelling loop tasks so
        that on restart each issue can be routed back to the correct phase.
        """
        self._stop_event.set()
        logger.info("Stop requested — terminating active processes")
        self._svc.planners.terminate()
        self._svc.agents.terminate()
        self._svc.reviewers.terminate()
        self._svc.hitl_runner.terminate()
        # #9911: the four runner sets above are only part of the picture —
        # acceptance_criteria / verification_judge / sentry / report_issue
        # (and any future stream_claude_process caller) register in the
        # runtime-wide registry; reap the union so nothing reparents to
        # launchd and burns CPU after "idle".
        reaped = reap_all_tracked_processes()
        if reaped:
            logger.info(
                "Stop: reaped %d subprocess group(s) beyond the runner-owned sets",
                reaped,
            )

        # #11535 stop fence: drop every driver and its ownership claim before
        # the loops are cancelled, so nothing is admitted or advanced after a
        # stop and no claim survives a drain. "Zero post-stop spawns" is one of
        # the counters the ADR-0137 B5 canary bar measures. No-op under
        # Classic, where no manager was ever constructed.
        if self._svc.driver_manager is not None:
            self._svc.driver_manager.release_all()
        self._svc.driver_ownership.release_all()

        # Checkpoint interrupted issues before cancelling tasks
        interrupted = await self._build_interrupted_issues()
        if interrupted:
            self._state.set_interrupted_issues(interrupted)
            logger.info(
                "Checkpointed %d interrupted issue(s): %s",
                len(interrupted),
                interrupted,
            )

        # Cancel loop tasks so _supervise_loops exits immediately
        for name, task in self._loop_tasks.items():
            if not task.done():
                task.cancel()
                logger.debug("Cancelled loop task %r", name)

        # Cancel the credit-failover switch-back probe if it is running (#10844).
        if (
            self._failover_probe_task is not None
            and not self._failover_probe_task.done()
        ):
            self._failover_probe_task.cancel()

        # Hindsight HTTP client removed in Phase 3 cutover — no close needed.

        await self._publish_status()

    async def _build_interrupted_issues(self) -> dict[int, str]:
        """Build a mapping of issue_number → phase for all in-flight issues.

        Called during shutdown after ``stop_event`` is set.  Phase workers
        check ``stop_event`` before modifying their ``_active_issues`` sets,
        so no new additions occur once shutdown begins — iteration is safe
        without holding the per-phase locks.  ``_active_issues_lock`` (the
        orchestrator-level lock) guards against concurrent calls to this
        method itself, not against phase-worker modifications.
        """
        async with self._active_issues_lock:
            interrupted: dict[int, str] = {}
            # Use IssueStore active tracking as the primary source.
            # ``get_active_issues`` is orchestrator-only — not on IssueStorePort.
            store: IssueStore = cast("IssueStore", self._svc.store)
            for issue_number, stage in store.get_active_issues().items():
                interrupted[issue_number] = stage
            # Also check in-memory tracking sets for issues not yet in the store
            for issue_number in self._svc.implementer.active_issues:
                if issue_number not in interrupted:
                    interrupted[issue_number] = "implement"
            for issue_number in self._svc.reviewer.active_issues:
                if issue_number not in interrupted:
                    interrupted[issue_number] = "review"
            for issue_number in self._hitl_ctrl.active_hitl_issues:
                if issue_number not in interrupted:
                    interrupted[issue_number] = "hitl"
            return interrupted

    # Alias used live by dashboard_routes/_control_routes.py:326
    request_stop = stop

    def reset(self) -> None:
        """Reset all mutable state so the orchestrator can be restarted.

        Every ``asyncio.Event`` field must be explicitly ``.clear()``'d here.
        Events retain their set state across stop/start cycles — omitting one
        causes waiters (e.g. ``_sleep_until_resume``) to return immediately on
        restart.  See #3119 / #3123.
        """
        self._stop_event.clear()
        self._credit_resume_event.clear()
        self._running = False
        self._auth_failed = False
        self._credits_paused_until = None
        self._credit_paused_provider = None
        # ``clear_active`` is orchestrator-only — not on IssueStorePort.
        cast("IssueStore", self._svc.store).clear_active()
        self._svc.implementer.active_issues.clear()
        self._svc.reviewer.active_issues.clear()
        self._hitl_ctrl.active_hitl_issues.clear()
        self._sync_active_issue_numbers()
        self._state.clear_interrupted_issues()

    def _restore_state(self) -> None:
        """Restore worker intervals, crash-recovered issues, interrupted issues, disabled workers, and background worker heartbeats."""
        self._state_restorer.restore_all(
            recovered_issues=self._recovered_issues,
            active_impl_issues=self._svc.implementer.active_issues,
            active_review_issues=self._svc.reviewer.active_issues,
            active_hitl_issues=self._hitl_ctrl.active_hitl_issues,
        )

    async def _start_session(self) -> None:
        """Create a new session log and publish SESSION_START."""
        repo_slug = self._config.repo.replace("/", "-")
        session_start_time = datetime.now(UTC)
        session_id = f"{repo_slug}-{session_start_time.strftime('%Y%m%dT%H%M%S')}"
        self._current_session = SessionLog(
            id=session_id,
            repo=self._config.repo,
            started_at=session_start_time.isoformat(),
        )
        self._session_issue_results = {}
        self._state.reset_session_counters(session_start_time.isoformat())
        self._state.save_session(self._current_session)
        self._bus.set_session_id(session_id)
        data: SessionStartPayload = {
            "session_id": session_id,
            "repo": self._config.repo,
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SESSION_START,
                session_id=session_id,
                data=data,
            )
        )

    async def _end_session(self) -> None:
        """Close the current session log and publish SESSION_END."""
        if not self._current_session:
            return
        self._current_session.ended_at = datetime.now(UTC).isoformat()
        self._current_session.issues_processed = list(
            self._session_issue_results.keys()
        )
        self._current_session.issues_succeeded = sum(
            1 for s in self._session_issue_results.values() if s
        )
        self._current_session.issues_failed = sum(
            1 for s in self._session_issue_results.values() if not s
        )
        self._current_session.status = SessionStatus.COMPLETED
        self._state.save_session(self._current_session)
        self._state.prune_sessions(
            self._config.repo, self._config.max_sessions_per_repo
        )
        data: SessionEndPayload = {
            "session_id": self._current_session.id,
            "status": "completed",
            "issues_processed": self._current_session.issues_processed,
            "issues_succeeded": self._current_session.issues_succeeded,
            "issues_failed": self._current_session.issues_failed,
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SESSION_END,
                session_id=self._current_session.id,
                data=data,
            )
        )
        self._current_session = None
        self._bus.set_session_id(None)

    def _warn_if_agents_md_missing(self) -> None:
        """Log a warning if AGENTS.md is absent from the repo root.

        AGENTS.md documents the prompt contracts for all agent roles.  Its
        absence means agent behaviour is undocumented and harder to audit or
        adapt.  Run ``make setup`` (copies AGENTS.md into the target repo) or
        copy AGENTS.md from the HydraFlow repo to resolve this.
        """
        agents_md = self._config.repo_root / "AGENTS.md"
        if not agents_md.is_file():
            logger.warning(
                "AGENTS.md not found in %s — agent prompt contracts are "
                "undocumented. Run `make setup` to sync it from HydraFlow.",
                self._config.repo_root,
            )

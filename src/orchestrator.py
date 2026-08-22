"""Main orchestrator loop — plan, implement, review, cleanup, repeat."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable, Coroutine, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import credit_failover
from adr_utils import is_adr_issue_title
from bg_worker_manager import BGWorkerManager
from config import HydraFlowConfig, resolve_maintenance_model
from event_loop_watchdog import build_event_loop_watchdog
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from hitl_controller import HITLController
from human_steering import apply_steering, resolve_redo_phase
from issue_store import STAGE_NAME_MAP, IssueStoreStage
from models import (
    BackgroundWorkerState,
    BackgroundWorkerStatusPayload,
    ErrorPayload,
    GitHubIssue,
    OrchestratorStatusPayload,
    Phase,
    PipelineStats,
    SessionEndPayload,
    SessionLog,
    SessionStartPayload,
    SessionStatus,
    StageStats,
    SteeringState,
    SystemAlertPayload,
    Task,
    ThroughputStats,
    WorkFn,
)
from phase_utils import (
    INFRA_FATAL_EXCEPTIONS,
    escalate_to_hitl,
    handle_pool_worker_exception,
    is_likely_bug,
    log_exception_with_bug_classification,
    release_batch_in_flight,
)
from runner_utils import (
    backend_probe_endpoint,
    harness_billing_provider,
    normalize_provider,
    reap_all_tracked_processes,
)
from service_registry import (
    ServiceRegistry,
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)
from state import StateTracker
from state_restorer import StateRestorer
from subprocess_util import (
    PROVIDER_ANTHROPIC,
    AuthenticationError,
    CreditExhaustedError,
    probe_auth_availability,
    probe_credit_availability,
)

if TYPE_CHECKING:
    from base_background_loop import BaseBackgroundLoop
    from epic import EpicManager
    from github_cache_loop import GitHubDataCache
    from issue_store import IssueStore
    from metrics_manager import MetricsManager
    from pr_manager import PRManager
    from run_recorder import RunRecorder
    from workspace import WorkspaceManager

logger = logging.getLogger("hydraflow.orchestrator")


def _log_deferred_task_failure(task: asyncio.Task[Any]) -> None:
    """Log unhandled exceptions from fire-and-forget background tasks (#6513)."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning("Deferred orchestrator task failed", exc_info=exc)


# Delay after a merge to allow GitHub to propagate the merge state.
_POST_MERGE_DELAY: int = 5

# Delay before restarting a loop whose AuthenticationError was refuted by the
# live probe (a transient blip). A restart with no delay would let a loop that
# runs-on-startup re-crash immediately while a sustained blip lasts, spinning
# the supervisor and storming WARNING logs — the same hot-loop pathology #9924
# guarded against on the credit false-positive path. The delay lives inside the
# recreated task, so it never blocks supervision of the other loops (#9621).
_AUTH_TRANSIENT_RESTART_DELAY_S: float = 30.0

# Loops whose primary LLM work routes through a per-role provider dial. Maps
# each loop to the ``HydraFlowConfig`` fields holding its dial and model. This
# includes the four core work loops as well as independently-routed maintenance
# loops; omitting a core loop here mis-scopes provider credit pauses even though
# its runner correctly routes the actual spawn.
# A loop that does MIXED work (dial'd one-shot + some harness spawns, e.g.
# pr_unsticker's HITL analysis) self-heals: while it survives an Anthropic pause
# its harness sub-call re-raises an ``anthropic`` signal that the already-active
# pause absorbs. Keep in sync with the ``*_provider`` dials in config.py.
_BACKEND_WORKER_LOOPS: dict[str, tuple[str, str]] = {
    "triage": ("triage_provider", "triage_model"),
    "plan": ("planner_provider", "planner_model"),
    "implement": ("implementation_provider", "model"),
    "review": ("review_provider", "review_model"),
    "repo_wiki": ("wiki_compilation_provider", "wiki_compilation_model"),
    "adr_reviewer": ("adr_review_provider", "adr_review_model"),
    "pr_unsticker": ("pr_unstick_provider", "background_model"),
    "term_proposer": ("term_proposer_provider", "term_proposer_model"),
    "entry_evidence": ("term_proposer_provider", "term_proposer_model"),
    "intervention_tally": ("maintenance_provider", "intervention_tally_model"),
    "sampled_audit": ("maintenance_provider", "sampled_audit_model"),
    "issue_refinement": ("maintenance_provider", "issue_refinement_model"),
    "skill_prompt_eval": ("maintenance_provider", "skill_prompt_refine_model"),
}

# Core work loops whose runner seams apply repo routing and credit failover.
# Used to distinguish a gateway transport (whose server owns the z.ai key) from
# a direct harness route (which still requires a local z.ai credential).
_PRIMARY_WORK_LOOP_TO_TOOL_FIELD: dict[str, str] = {
    "triage": "triage_tool",
    "plan": "planner_tool",
    "implement": "implementation_tool",
    "review": "review_tool",
}


class HydraFlowOrchestrator:
    """Coordinates the full HydraFlow pipeline.

    Each phase runs as an independent polling loop so new work is picked
    up continuously — planner, implementer, and reviewer all run
    concurrently without waiting on each other.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus | None = None,
        state: StateTracker | None = None,
        pipeline_enabled: bool = True,
        *,
        services: ServiceRegistry | None = None,
    ) -> None:
        self._config = config
        # Register config for module-level free-function helpers (e.g.
        # trace_collector.emit_loop_subprocess_trace, spec §4.11 point 3).
        # The orchestrator is the single process-wide lifecycle owner.
        from trace_collector import set_active_config  # noqa: PLC0415

        set_active_config(config)
        self._bus = event_bus or EventBus()
        self._state = state or build_state_tracker(config)
        self._dashboard: object | None = None
        self._active_issues_lock = asyncio.Lock()
        # Issues recovered from persisted state on startup (one-cycle grace period)
        self._recovered_issues: set[int] = set()
        # Stop mechanism for dashboard control
        self._stop_event = asyncio.Event()
        self._running = False
        # Pipeline gate — when False, pipeline loops sleep until play is pressed.
        # Defaults to True for headless mode / tests; dashboard passes False.
        self._pipeline_enabled = pipeline_enabled
        # Auth failure flag — set when a loop crashes due to AuthenticationError
        self._auth_failed = False
        # Credit pause — set when API credits are exhausted
        self._credits_paused_until: datetime | None = None
        # Which billing provider the active pause is scoped to (#9807): a backend
        # name ("zai"/"kimi"/"openrouter") pauses only loops routed there;
        # "anthropic" pauses everything except surviving backend workers; ``None``
        # is the global fallback (unknown provider → pause all). Purely for
        # status/UI + observability; the affected-loop set is computed at pause
        # time and threaded through resume.
        self._credit_paused_provider: str | None = None
        # Per-source last false-positive suppression (#9888 throttle).
        self._credit_fp_last: dict[str, datetime] = {}
        self._credit_pause_lock = asyncio.Lock()
        self._credit_resume_event = asyncio.Event()
        # Credit failover (#10844): the switch-back probe task, live only while
        # work is rerouted to GLM (credit_failover module holds the routing flag).
        self._failover_probe_task: asyncio.Task[None] | None = None
        # Session tracking
        self._current_session: SessionLog | None = None
        self._session_issue_results: dict[int, bool] = {}
        # Loop tasks (set by _supervise_loops for stop() to cancel)
        self._loop_tasks: dict[str, asyncio.Task[None]] = {}
        # Loop factories (retained by _supervise_loops so restart_loop_task
        # can cancel-and-recreate a silently-stalled loop task)
        self._loop_factories: dict[str, Callable[[], Coroutine[Any, Any, None]]] = {}
        # Strong references for fire-and-forget background tasks (#6513) —
        # without this the GC can collect the Task before it completes.
        self._deferred_tasks: set[asyncio.Task[None]] = set()

        # Build all services via the factory (or use what was passed in).
        # Production callers pass nothing → build a real registry here.
        # The sandbox entrypoint (mockworld.sandbox_main, Task 1.10) passes
        # a pre-built registry containing Fakes so a single ServiceRegistry
        # is wired through both layers without any conditional in the
        # production code path.
        if services is None:
            services = build_services(
                config,
                self._bus,
                self._state,
                self._stop_event,
                WorkerRegistryCallbacks(
                    update_status=self.update_bg_worker_status,
                    is_enabled=self.is_bg_worker_enabled,
                    get_interval=self.get_bg_worker_interval,
                    get_watchdog_timeout=self.get_bg_worker_timeout,
                ),
                active_issues_cb=self._sync_active_issue_numbers,
            )

        # Store the service registry directly — access via self._svc.<name>
        self._svc: ServiceRegistry = services
        # Local alias kept for downstream readability (the registry was
        # previously named ``svc`` throughout this constructor).
        svc = services

        # Extracted component managers
        bg_loop_registry: dict[str, BaseBackgroundLoop] = {
            "pr_unsticker": svc.pr_unsticker_loop,
            "merge_state_watcher": svc.merge_state_watcher_loop,
            "report_issue": svc.report_issue_loop,
            "epic_monitor": svc.epic_monitor_loop,
            "epic_sweeper": svc.epic_sweeper_loop,
            "workspace_gc": svc.workspace_gc_loop,
            "runs_gc": svc.runs_gc_loop,
            "adr_reviewer": svc.adr_reviewer_loop,
            "health_monitor": svc.health_monitor_loop,
            "dependabot_merge": svc.dependabot_merge_loop,
            "staging_promotion": svc.staging_promotion_loop,
            "staging_bisect": svc.staging_bisect_loop,
            "stale_issue": svc.stale_issue_loop,
            "log_ingest": svc.log_ingest_loop,
            "github_cache": svc.github_cache_loop,
            "stale_issue_gc": svc.stale_issue_gc_loop,
            "gate_health": svc.gate_health_loop,
            "pr_red_repair": svc.pr_red_repair_loop,
            "erosion_metrics": svc.erosion_metrics_loop,
            "fail_open_monitor": svc.fail_open_monitor_loop,
            "escape_ledger": svc.escape_ledger_loop,
            "intervention_tally": svc.intervention_tally_loop,
            "sampled_audit": svc.sampled_audit_loop,
            "second_order_vitals": svc.second_order_vitals_loop,
            "issue_refinement": svc.issue_refinement_loop,
            "ci_monitor": svc.ci_monitor_loop,
            "branch_protection_auditor": svc.branch_protection_auditor_loop,
            "goal_supervisor": svc.goal_supervisor_loop,
            "rails_drift_caretaker": svc.rails_drift_caretaker_loop,
            "gate_activator": svc.gate_activator_loop,
            "security_patch": svc.security_patch_loop,
            "repo_wiki": svc.repo_wiki_loop,
            "diagnostic": svc.diagnostic_loop,
            "retrospective": svc.retrospective_loop,
            "principles_audit": svc.principles_audit_loop,
            "flake_tracker": svc.flake_tracker_loop,
            "skill_prompt_eval": svc.skill_prompt_eval_loop,
            "fake_coverage_auditor": svc.fake_coverage_auditor_loop,
            "adr_conformance": svc.adr_conformance_loop,
            "auto_tighten": svc.auto_tighten_loop,
            "memory_backlog": svc.memory_backlog_loop,
            "rc_budget": svc.rc_budget_loop,
            "wiki_rot_detector": svc.wiki_rot_detector_loop,
            "trust_fleet_sanity": svc.trust_fleet_sanity_loop,
            "label_drift_watcher": svc.label_drift_watcher_loop,
            "contract_refresh": svc.contract_refresh_loop,
            "corpus_learning": svc.corpus_learning_loop,
            "auto_agent_preflight": svc.auto_agent_preflight_loop,
            "gateway_coverage": svc.gateway_coverage_loop,
            "detector_calibration": svc.detector_calibration_loop,
            "sandbox_failure_fixer": svc.sandbox_failure_fixer_loop,
            "disturbance_dampener": svc.disturbance_dampener_loop,
            "human_steering": svc.human_steering_loop,
            "diagram_loop": svc.diagram_loop,
            "pricing_refresh": svc.pricing_refresh_loop,
            "cost_budget_watcher": svc.cost_budget_watcher_loop,
            "term_proposer": svc.term_proposer_loop,
            "term_pruner": svc.term_pruner_loop,
            "edge_proposer": svc.edge_proposer_loop,
            "live_corpus_replay": svc.live_corpus_replay_loop,
            "triage_retry": svc.triage_retry_loop,
            "convergence_oscillation": svc.convergence_oscillation_loop,
            "entry_evidence": svc.entry_evidence_loop,
            "fitness_scorecard": svc.fitness_scorecard_loop,
        }
        self._bg_workers = BGWorkerManager(config, self._state, bg_loop_registry)
        # The restart verb reads self._loop_tasks/_loop_factories lazily, so
        # binding it here (before _supervise_loops populates them) is safe.
        self._bg_workers.set_restart_cb(self.restart_loop_task)
        svc.fitness_scorecard_loop.set_loops(bg_loop_registry)
        # Loops that need a reference to BGWorkerManager cannot take one
        # at construction time (chicken-and-egg: BGWorkerManager takes the
        # loop registry). Inject it now, post-construction.
        svc.trust_fleet_sanity_loop.set_bg_workers(self._bg_workers)
        svc.health_monitor_loop.set_bg_workers(self._bg_workers)
        svc.cost_budget_watcher_loop.set_bg_workers(self._bg_workers)
        svc.goal_supervisor_loop.set_bg_workers(self._bg_workers)
        self._hitl_ctrl = HITLController(svc.hitl_phase, svc.fetcher, config.hitl_label)
        self._state_restorer = StateRestorer(self._state, self._bus, self._bg_workers)

    @property
    def event_bus(self) -> EventBus:
        """Expose event bus for dashboard integration."""
        return self._bus

    @property
    def issue_store(self) -> IssueStore:
        """Expose the centralized issue store for dashboard integration.

        Narrowed from ``IssueStorePort`` to the concrete ``IssueStore``
        because dashboard handlers use orchestrator-only methods
        (``get_active_issues``, ``get_merged_numbers``, etc.) that are
        intentionally excluded from the Port surface.
        """
        return cast("IssueStore", self._svc.store)

    @property
    def state(self) -> StateTracker:
        """Expose state for dashboard integration."""
        return self._state

    @property
    def github_cache(self) -> GitHubDataCache:
        """Expose GitHub data cache for dashboard endpoints."""
        return self._svc.github_cache

    @property
    def run_recorder(self) -> RunRecorder:
        """Expose run recorder for dashboard API."""
        return self._svc.run_recorder

    @property
    def metrics_manager(self) -> MetricsManager:
        """Expose metrics manager for dashboard API."""
        return self._svc.metrics_manager

    @property
    def epic_manager(self) -> EpicManager:
        """Expose epic manager for dashboard API."""
        return self._svc.epic_manager

    @property
    def running(self) -> bool:
        """Whether the orchestrator is currently executing."""
        return self._running

    @property
    def pipeline_enabled(self) -> bool:
        """Whether the pipeline loops should process work."""
        return self._pipeline_enabled

    @pipeline_enabled.setter
    def pipeline_enabled(self, value: bool) -> None:
        was_disabled = not self._pipeline_enabled
        self._pipeline_enabled = value
        if value and was_disabled and self._running:
            # Pipeline just turned on — run deferred repo init in background.
            # Store the Task ref (#6513) so the GC can't collect it mid-flight
            # and attach a done_callback that logs unhandled exceptions.
            task = asyncio.create_task(self._deferred_pipeline_start())
            self._deferred_tasks.add(task)
            task.add_done_callback(self._deferred_tasks.discard)
            task.add_done_callback(_log_deferred_task_failure)

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

    @property
    def current_session_id(self) -> str | None:
        """Return the active session ID, or None."""
        return self._current_session.id if self._current_session else None

    def _has_active_processes(self) -> bool:
        """Return True if any runner pool still has live subprocesses."""
        return bool(
            self._svc.planners.active_count
            or self._svc.agents.active_count
            or self._svc.reviewers.active_count
            or self._svc.hitl_runner.active_count
        )

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
        if self._is_slug_blocked(slug):
            logger.debug("Skipping %s — onboarding blocked", slug)
            return False
        return await inner()

    @property
    def credits_paused_until(self) -> datetime | None:
        """The UTC datetime when credit pause ends, or ``None``."""
        if (
            self._credits_paused_until is not None
            and self._credits_paused_until > datetime.now(UTC)
        ):
            return self._credits_paused_until
        return None

    @property
    def credits_paused_provider(self) -> str | None:
        """The billing provider the ACTIVE credit pause is scoped to, or ``None``
        (no active pause, or a global/legacy pause). Surfaced in the status
        payload so the UI can show *which* backend is paused (#9807)."""
        if self.credits_paused_until is not None:
            return self._credit_paused_provider
        return None

    def clear_credit_pause(self) -> None:
        """Clear a credit pause early, waking ``_sleep_until_resume``."""
        self._credits_paused_until = None
        self._credit_paused_provider = None
        self._credit_resume_event.set()

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

    @property
    def human_input_requests(self) -> dict[int, str]:
        """Pending questions for the human operator."""
        return self._hitl_ctrl.human_input_requests

    def provide_human_input(self, issue_number: int, answer: str) -> None:
        """Provide an answer to a paused agent's question."""
        self._hitl_ctrl.provide_human_input(issue_number, answer)

    def submit_hitl_correction(self, issue_number: int, correction: str) -> None:
        """Store a correction for a HITL issue to guide retry."""
        self._hitl_ctrl.submit_correction(issue_number, correction)

    def get_hitl_status(self, issue_number: int) -> str:
        """Return the HITL status for an issue."""
        return self._hitl_ctrl.get_status(issue_number)

    def skip_hitl_issue(self, issue_number: int) -> None:
        """Remove an issue from HITL tracking."""
        self._hitl_ctrl.skip_issue(issue_number)

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

    def try_clear_credit_pause(self) -> bool:
        """Attempt to clear the credit pause and resume loops early.

        Returns ``True`` if a pause was active and the resume signal was sent,
        ``False`` if no pause was active.
        """
        if self._credits_paused_until is None:
            return False
        self._credit_resume_event.set()
        return True

    @property
    def _active_hitl_issues(self) -> set[int]:
        """Backward-compatible access to HITL active issues."""
        return self._hitl_ctrl.active_hitl_issues

    @property
    def _hitl_corrections(self) -> dict[int, str]:
        """Backward-compatible access to HITL corrections dict."""
        return self._hitl_ctrl.hitl_corrections

    async def _apply_human_steering(self) -> None:
        """Actuate pending steering directives for active issues (ADR-0099 #4).

        Pure decision logic lives in ``human_steering.apply_steering``; this
        method only enumerates active issues and enacts the decision —
        phase-boundary actuation, not a mid-phase interrupt (a running phase
        always completes first; see steering-global-constraints). No-op when
        ``human_steering_enabled`` is off.

        - ``skip`` (paused): drop from this cycle — simply don't re-enqueue.
        - ``park`` (abort): escalate to HITL (``hitl_label``) with a distinct
          ``operator-abort`` origin so the issue leaves active scheduling but
          a human can un-escalate it later, exactly like any other HITL
          escalation — while the dashboard can still tell an operator abort
          apart from a failure-driven escalation. Guarded for idempotency: a
          new ``/abort`` on an issue already at the ``operator-abort`` origin
          does not re-fire the (non-idempotent) escalation.
        - ``redo_phase``: resolve a dashboard-facing or internal phase token
          (``human_steering.resolve_redo_phase``) then re-enqueue to the
          resolved phase (when valid and under the redo cap) and persist the
          incremented ``redo_count`` with ``redo_phase`` cleared so it isn't
          replayed next cycle. An unrecognized token or a redo dropped by the
          cap gets one operator-facing PR comment (gated on the same
          ``redo_phase`` high-water-mark so it posts once, not every tick)
          and ``redo_phase`` is cleared the same way.
        """
        if not self._config.human_steering_enabled:
            return

        known_phases = {stage.value for stage in IssueStoreStage} - {
            IssueStoreStage.MERGED.value
        }
        store: IssueStore = cast("IssueStore", self._svc.store)
        active_issues = store.get_active_issues()
        if not active_issues:
            return

        for issue_number in active_issues:
            key = str(issue_number)
            prev = self._state.get_human_steering(key)
            raw_token = prev.redo_phase
            resolved_phase = (
                resolve_redo_phase(raw_token) if raw_token is not None else None
            )
            lookup_state = (
                prev
                if raw_token is None
                else SteeringState(
                    guidance=prev.guidance,
                    flow=prev.flow,
                    redo_phase=resolved_phase,
                    redo_count=prev.redo_count,
                    last_applied_ts=prev.last_applied_ts,
                )
            )
            decision = apply_steering(
                lookup_state, key, known_phases, self._config.human_steering_max_redos
            )

            if decision.park:
                # Idempotency guard: `escalate_to_hitl` increments a
                # lifetime counter on every call, so a fresh `/abort` on an
                # issue that's already parked with the operator-abort origin
                # must not re-fire it (the steering high-water-mark already
                # prevents the *same* comment from re-triggering; this
                # guards a *new* /abort on an already-aborted issue).
                if self._state.get_hitl_origin(issue_number) != "operator-abort":
                    await escalate_to_hitl(
                        self._state,
                        self._svc.prs,
                        issue_number,
                        cause="/abort steering directive",
                        origin_label="operator-abort",
                        hitl_label=self._config.hitl_label[0],
                    )
                continue

            if decision.skip:
                # Paused — leave the issue exactly where it is this cycle;
                # the next phase-poll simply won't pick it up as new work.
                continue

            if raw_token is not None and decision.redo_phase is None:
                # Redo was present this cycle but dropped: either the token
                # didn't resolve to a known phase, or it resolved but was
                # dropped by the redo cap. Gated on raw_token being freshly
                # consumed (not None), so this fires once per directive, not
                # every tick — matches the redo high-water-mark semantics.
                reason = (
                    "unknown phase" if resolved_phase is None else "redo cap reached"
                )
                # Derive the operator-facing list from known_phases (the same
                # source of truth apply_steering validates against) mapped
                # through STAGE_NAME_MAP to dashboard-facing display names,
                # so it can't drift out of sync with what /redo actually
                # accepts (e.g. missing "triage", the display name for FIND).
                valid_phase_names = ", ".join(
                    STAGE_NAME_MAP[stage]
                    for stage in IssueStoreStage
                    if stage.value in known_phases
                )
                await self._svc.prs.post_comment(
                    issue_number,
                    f"⚠️ steering: /redo '{raw_token}' not applied — {reason}; "
                    f"valid: {valid_phase_names}",
                )
                self._state.set_human_steering(
                    key,
                    SteeringState(
                        guidance=prev.guidance,
                        flow=prev.flow,
                        redo_phase=None,
                        redo_count=decision.new_redo_count,
                        last_applied_ts=prev.last_applied_ts,
                    ),
                )
                continue

            if decision.redo_phase is not None:
                task = store.get_cached(issue_number)
                if task is not None:
                    store.enqueue_transition(task, decision.redo_phase)
                self._state.set_human_steering(
                    key,
                    SteeringState(
                        guidance=prev.guidance,
                        flow=prev.flow,
                        redo_phase=None,
                        redo_count=decision.new_redo_count,
                        last_applied_ts=prev.last_applied_ts,
                    ),
                )

    def _sync_active_issue_numbers(self) -> None:
        """Persist the combined active issue set to state.

        The orchestrator is the sole writer to ``set_active_issue_numbers``.
        Phases maintain their own ``_active_issues`` sets and invoke this
        callback when they change; the orchestrator merges all three sources.

        Safety: this method is synchronous with no ``await`` points, so the
        asyncio event loop cannot interleave it with coroutines that modify
        the active-issue sets.  The set union + list conversion runs
        atomically from the event loop's perspective.
        """
        self._state.set_active_issue_numbers(
            list(
                self._svc.implementer.active_issues
                | self._svc.reviewer.active_issues
                | self._hitl_ctrl.active_hitl_issues
            )
        )

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

    async def run(self) -> None:
        """Run three independent, continuous loops — plan, implement, review.

        Each loop polls for its own work on ``poll_interval`` and processes
        whatever it finds.  No phase blocks another; new issues are picked
        up as soon as they arrive.  Loops run until explicitly stopped.
        """
        self._stop_event.clear()
        self._running = True
        # #9552: arm the thread-level event-loop freeze detector before any
        # loop starts, so a synchronous block anywhere in the fleet is
        # observable from OUTSIDE the (then-frozen) event loop. Builder
        # returns None when disabled or under pytest; start() is a passive
        # no-op when another orchestrator on this process already armed one.
        event_loop_watchdog = build_event_loop_watchdog(self._config)
        if event_loop_watchdog is not None:
            event_loop_watchdog.start()
        try:
            self._restore_state()
            self._rearm_failover_probe_if_active()
            await self._publish_status()
            # Seed the full loop registry onto the bus before any loop ticks so
            # the operator console's loop-health count is accurate + stable from
            # boot rather than climbing as slow loops report (#10556).
            await self._seed_background_worker_statuses()
            logger.info(
                "HydraFlow starting — repo=%s label=%s workers=%d poll=%ds pipeline=%s",
                self._config.repo,
                ",".join(self._config.ready_label),
                self._config.max_workers,
                self._config.poll_interval,
                "enabled" if self._pipeline_enabled else "paused",
            )

            # Only initialize the repo and create a session when the pipeline
            # is enabled.  When pipeline_enabled=False (dashboard mode), the
            # orchestrator only runs background workers — no issue fetching,
            # no repo sanitization, no session.
            session_started = False
            if self._pipeline_enabled:
                # Concrete-only setup methods — not on Port. See _deferred_pipeline_start.
                workspaces: WorkspaceManager = cast(
                    "WorkspaceManager", self._svc.workspaces
                )
                prs: PRManager = cast("PRManager", self._svc.prs)
                await workspaces.sanitize_repo()
                await prs.ensure_labels_exist()
                await workspaces.enable_rerere()
                self._warn_if_agents_md_missing()
                await self._start_session()
                session_started = True

            try:
                await self._supervise_loops()
            finally:
                if session_started:
                    await self._end_session()
                self._svc.planners.terminate()
                self._svc.agents.terminate()
                self._svc.reviewers.terminate()
                self._svc.hitl_runner.terminate()
                with contextlib.suppress(Exception):
                    # Same concrete-only narrowing as the bootstrap above.
                    await cast("WorkspaceManager", self._svc.workspaces).sanitize_repo()
                await asyncio.sleep(0)
                self._running = False
                await self._publish_status()
                logger.info("HydraFlow stopped")
        finally:
            # #9552: disarm the freeze detector on ANY exit path — the thread
            # exits within one poll tick of the stop event; a leaked daemon
            # thread can't wedge teardown, but a prompt stop keeps restarts
            # (and tests that force=True the builder) clean.
            if event_loop_watchdog is not None:
                event_loop_watchdog.stop()
            # Safety net: if run() is cancelled or raises during the setup
            # phase above (before the supervise-loops try-block), the inner
            # finally never executes and the line would stay stuck reporting
            # running=True forever — a stopped factory line shows green on the
            # dashboard with last_error=None. Guarantee the flag clears on ANY
            # exit. Idempotent with the inner finally on the normal shutdown
            # path. See `rt.start()` -> wait_for cancellation in repo_runtime.
            self._running = False

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

    async def _handle_credit_exhaustion(
        self,
        exc: CreditExhaustedError,
        loop_name: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Pause on a corroborated credit signal; otherwise restart the loop.

        A probe-refuted (false-positive) signal must not leave the crashed
        loop's completed-with-exception task orphaned in ``_supervise_loops``'s
        task map: the supervisor would re-observe the same dead task every
        iteration and hot-loop the credit handler (alert storm), and the phase
        would stay permanently dead. Recreating the task via ``_restart_loop``
        — the same path used for any other loop crash — kills the hot loop and
        self-heals the phase. See #9924.

        Credit failover (#10844): an *authoritative* Claude cap short-circuits to
        engaging GLM failover and restarting the crashed loop NOW — it re-runs
        routed to GLM (base_runner reroutes while failover is active) instead of
        pausing the factory. Everything else (prose-only signals, non-Claude
        caps, no zai key, disabled) falls through to the unchanged pause logic.
        """
        if await self._maybe_engage_failover(exc, loop_name):
            await self._restart_loop(loop_name, exc, tasks, loop_factories)
            return
        paused = await self._pause_for_credits(exc, loop_name, tasks, loop_factories)
        if not paused:
            # Suppressed false positive: restart with a delay so a loop that
            # re-raises the same quoted-prose signal cannot tight-spin the
            # supervisor (#9888). The delay lives inside the restarted task,
            # never blocking supervision of other loops.
            await self._restart_loop(
                loop_name,
                exc,
                tasks,
                loop_factories,
                restart_delay=min(
                    float(self._config.credit_fp_suppress_cooldown_seconds), 60.0
                ),
            )

    async def _maybe_engage_failover(
        self, exc: CreditExhaustedError, loop_name: str | None = None
    ) -> bool:
        """Engage GLM failover for an authoritative Claude credit cap (#10844).

        Returns ``True`` when the caller should restart the crashed loop NOW (it
        re-runs routed to GLM) instead of pausing. Returns ``False`` — falling
        through to the unchanged pause/probe logic — for anything that is not a
        clear Claude cap we can fail over: the feature disabled, a non-Claude
        (zai/kimi) cap, a prose-only signal that still needs corroboration, or no
        a usable route to z.ai. Direct harness routes still require a local z.ai
        credential. A gateway-routed core work loop does not: the gateway owns
        the provider credential and the restarted worker receives only a new
        z.ai-bound virtual key. Idempotent while already failed over: it just
        re-signals "restart on GLM".
        """
        if not self._config.credit_failover_enabled:
            return False
        provider = getattr(exc, "provider", PROVIDER_ANTHROPIC) or PROVIDER_ANTHROPIC
        if provider not in (PROVIDER_ANTHROPIC, "claude"):
            return False
        if not getattr(exc, "authoritative", False):
            return False
        gateway_route = self._loop_uses_gateway_transport(loop_name)
        if not credit_failover.zai_key_present() and not gateway_route:
            return False
        if credit_failover.is_active():
            # Already failed over (possibly engaged by another repo's orchestrator
            # — the flag is process-global). Ensure THIS orchestrator has a live
            # switch-back probe too, so it isn't left to whichever instance first
            # observed the cap. Idempotent when a probe is already running.
            self._start_failover_probe()
            return True
        now = datetime.now(UTC)
        resume_at = self._compute_resume_time(exc)
        credit_failover.engage(
            now=now,
            resume_at=resume_at if resume_at > now else None,
            cooldown_minutes=int(self._config.credit_failover_cooldown_minutes),
        )
        logger.warning(
            "Claude credit cap (provider=%s) — engaging GLM failover; work "
            "reroutes to %s. First Claude switch-back probe at %s.",
            provider,
            self._config.credit_failover_model,
            credit_failover.status().probe_after,
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "message": (
                        "Claude credits exhausted — failing over to GLM "
                        f"({self._config.credit_failover_model}); work continues."
                    ),
                    "provider": provider,
                    "severity": "warning",
                },
            )
        )
        self._start_failover_probe()
        return True

    def _start_failover_probe(self) -> None:
        """Start the switch-back probe task if one is not already running."""
        if (
            self._failover_probe_task is not None
            and not self._failover_probe_task.done()
        ):
            return
        self._failover_probe_task = asyncio.create_task(
            self._run_failover_probe(), name="hydraflow-credit-failover-probe"
        )

    def _rearm_failover_probe_if_active(self) -> None:
        """Re-arm the switch-back probe on startup when failover is engaged (#10844).

        The failover flag is a process-global that survives an in-process
        stop/start (and is shared across orchestrators in multi-repo mode). If a
        prior run left it engaged, the probe must be re-armed here — otherwise a
        restart while failed over leaves work silently pinned to GLM: every spawn
        reroutes before it can raise a fresh ``CreditExhaustedError``, so
        ``_maybe_engage_failover`` (which arms the probe) is never reached again.
        Idempotent when a probe is already live.
        """
        if credit_failover.is_active():
            self._start_failover_probe()

    async def _run_failover_probe(self) -> None:
        """Poll for Claude recovery while failover is active; clear on success."""
        while credit_failover.is_active() and not self._stop_event.is_set():
            if await self._probe_claude_for_switchback():
                return
            # Poll no faster than a minute; ``_sleep_or_stop`` wakes on shutdown.
            await self._sleep_or_stop(60.0)

    async def _probe_claude_for_switchback(self) -> bool:
        """One switch-back attempt. Returns ``True`` when failover was cleared.

        Only probes once the scheduled ``probe_after`` has arrived (the error's
        reset time, or the cooldown). A successful probe clears failover so work
        routes back to Claude; the next real Claude spawn is the true arbiter (a
        probe cannot see a *weekly* cap), and if it re-caps, failover re-engages.
        A failed probe pushes the next attempt out by a cooldown.
        """
        now = datetime.now(UTC)
        if not credit_failover.probe_due(now):
            return False
        base_url, api_key = backend_probe_endpoint(PROVIDER_ANTHROPIC, self._config)
        available = await probe_credit_availability(
            PROVIDER_ANTHROPIC, base_url=base_url, api_key=api_key
        )
        if available:
            credit_failover.clear()
            logger.warning(
                "Claude credit probe succeeded — clearing GLM failover; work "
                "returns to Claude."
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "message": "Claude credits recovered — switching back from GLM.",
                        "provider": PROVIDER_ANTHROPIC,
                        "severity": "info",
                    },
                )
            )
            return True
        credit_failover.advance_probe(
            now=now, cooldown_minutes=int(self._config.credit_failover_cooldown_minutes)
        )
        return False

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

    def stage_loop_names_and_factories(
        self,
    ) -> list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]]:
        """The pipeline stage loops this factory will run (#11535).

        Exposed rather than inlined so the default-off invariant is directly
        assertable: with Classic defaults this returns exactly today's four
        stage loops and no driver loop, which is the whole "nothing changes for
        an operator who does not opt in" claim, checked rather than argued.
        """
        if self._svc.driver_manager is not None:
            return [("issue_driver", self._issue_driver_loop)]
        return [
            ("plan", self._plan_loop),
            ("implement", self._implement_loop),
            ("review", self._review_loop),
            ("hitl", self._hitl_loop),
        ]

    async def _supervise_loops(self) -> None:
        """Run all loops plus the IssueStore poller, restarting any that crash."""

        async def _store_loop() -> None:
            # Only poll GitHub for issues when pipeline is enabled
            while not self._stop_event.is_set():
                if self._pipeline_enabled:
                    # ``start`` is the long-running poller — orchestrator-only
                    # method, not on IssueStorePort.
                    await cast("IssueStore", self._svc.store).start(self._stop_event)
                    return
                await self._sleep_or_stop(self._config.poll_interval)

        # #11535: the pipeline half of the fleet depends on the scheduling
        # model, and the two are mutually exclusive by construction. Under
        # Classic the four stage loops run exactly as they always have. Under
        # ``issue_controller`` they are replaced by a single driver loop, so an
        # issue cannot be claimed by both a stage pool and a driver — the
        # duplicate-owner hazard is removed structurally rather than by a check
        # that could be forgotten on a new intake path. Triage stays Classic in
        # both: an issue is not driver-owned until triage has decided it is
        # workable at all.
        stage_loops = self.stage_loop_names_and_factories()
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = [
            ("store", _store_loop),
            ("triage", self._triage_loop),
            *stage_loops,
            ("human_steering_actuator", self._human_steering_actuator_loop),
            ("pr_unsticker", self._svc.pr_unsticker_loop.run),
            ("merge_state_watcher", self._svc.merge_state_watcher_loop.run),
            ("report_issue", self._svc.report_issue_loop.run),
            ("epic_monitor", self._svc.epic_monitor_loop.run),
            ("epic_sweeper", self._svc.epic_sweeper_loop.run),
            ("workspace_gc", self._svc.workspace_gc_loop.run),
            ("runs_gc", self._svc.runs_gc_loop.run),
            ("adr_reviewer", self._svc.adr_reviewer_loop.run),
            ("health_monitor", self._svc.health_monitor_loop.run),
            ("dependabot_merge", self._svc.dependabot_merge_loop.run),
            ("staging_promotion", self._svc.staging_promotion_loop.run),
            ("staging_bisect", self._svc.staging_bisect_loop.run),
            ("stale_issue", self._svc.stale_issue_loop.run),
            ("log_ingest", self._svc.log_ingest_loop.run),
            ("github_cache", self._svc.github_cache_loop.run),
            ("pipeline_poller", self._pipeline_stats_loop),
            ("diagnostic", self._svc.diagnostic_loop.run),
            ("ci_monitor", self._svc.ci_monitor_loop.run),
            (
                "branch_protection_auditor",
                self._svc.branch_protection_auditor_loop.run,
            ),
            ("goal_supervisor", self._svc.goal_supervisor_loop.run),
            (
                "rails_drift_caretaker",
                self._svc.rails_drift_caretaker_loop.run,
            ),
            ("gate_activator", self._svc.gate_activator_loop.run),
            ("repo_wiki", self._svc.repo_wiki_loop.run),
            ("security_patch", self._svc.security_patch_loop.run),
            ("stale_issue_gc", self._svc.stale_issue_gc_loop.run),
            ("gate_health", self._svc.gate_health_loop.run),
            ("pr_red_repair", self._svc.pr_red_repair_loop.run),
            ("erosion_metrics", self._svc.erosion_metrics_loop.run),
            ("fail_open_monitor", self._svc.fail_open_monitor_loop.run),
            ("escape_ledger", self._svc.escape_ledger_loop.run),
            ("intervention_tally", self._svc.intervention_tally_loop.run),
            ("sampled_audit", self._svc.sampled_audit_loop.run),
            ("second_order_vitals", self._svc.second_order_vitals_loop.run),
            ("issue_refinement", self._svc.issue_refinement_loop.run),
            ("retrospective", self._svc.retrospective_loop.run),
            ("principles_audit", self._svc.principles_audit_loop.run),
            ("flake_tracker", self._svc.flake_tracker_loop.run),
            ("skill_prompt_eval", self._svc.skill_prompt_eval_loop.run),
            ("fake_coverage_auditor", self._svc.fake_coverage_auditor_loop.run),
            ("adr_conformance", self._svc.adr_conformance_loop.run),
            ("auto_tighten", self._svc.auto_tighten_loop.run),
            ("memory_backlog", self._svc.memory_backlog_loop.run),
            ("rc_budget", self._svc.rc_budget_loop.run),
            ("wiki_rot_detector", self._svc.wiki_rot_detector_loop.run),
            ("trust_fleet_sanity", self._svc.trust_fleet_sanity_loop.run),
            ("label_drift_watcher", self._svc.label_drift_watcher_loop.run),
            ("contract_refresh", self._svc.contract_refresh_loop.run),
            ("corpus_learning", self._svc.corpus_learning_loop.run),
            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),
            ("gateway_coverage", self._svc.gateway_coverage_loop.run),
            ("detector_calibration", self._svc.detector_calibration_loop.run),
            ("sandbox_failure_fixer", self._svc.sandbox_failure_fixer_loop.run),
            ("disturbance_dampener", self._svc.disturbance_dampener_loop.run),
            ("human_steering", self._svc.human_steering_loop.run),
            ("diagram_loop", self._svc.diagram_loop.run),
            ("pricing_refresh", self._svc.pricing_refresh_loop.run),
            ("cost_budget_watcher", self._svc.cost_budget_watcher_loop.run),
            ("term_proposer", self._svc.term_proposer_loop.run),
            ("term_pruner", self._svc.term_pruner_loop.run),
            ("edge_proposer", self._svc.edge_proposer_loop.run),
            ("live_corpus_replay", self._svc.live_corpus_replay_loop.run),
            ("triage_retry", self._svc.triage_retry_loop.run),
            ("convergence_oscillation", self._svc.convergence_oscillation_loop.run),
            ("entry_evidence", self._svc.entry_evidence_loop.run),
            ("fitness_scorecard", self._svc.fitness_scorecard_loop.run),
        ]

        # Hindsight WAL replay loop removed in Phase 3 cutover — the wiki
        # pipeline doesn't need a replay loop.
        known_worker_names = {n for n, _ in loop_factories}
        self._state_restorer.prune_stale_disabled_workers(known_worker_names)
        self._state_restorer.prune_stale_worker_states(known_worker_names)
        self._loop_factories = dict(loop_factories)
        tasks: dict[str, asyncio.Task[None]] = {}
        for name, factory in loop_factories:
            tasks[name] = asyncio.create_task(factory(), name=f"hydraflow-{name}")
        self._loop_tasks = tasks

        try:
            while not self._stop_event.is_set():
                done, _ = await asyncio.wait(
                    tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    name = task.get_name().removeprefix("hydraflow-")
                    if self._stop_event.is_set():
                        break
                    if tasks.get(name) is not task:
                        # Externally restarted (restart_loop_task) — the
                        # replacement is already registered and supervised;
                        # this is the drained old task. Calling .exception()
                        # on it would raise CancelledError here.
                        continue
                    if task.cancelled():
                        # Cancelled outside shutdown and not replaced —
                        # crash-equivalent; recreate to maintain supervision.
                        logger.warning(
                            "Loop %r was cancelled unexpectedly — restarting",
                            name,
                        )
                        factory_fn = dict(loop_factories)[name]
                        tasks[name] = asyncio.create_task(
                            factory_fn(), name=f"hydraflow-{name}"
                        )
                        break
                    exc = task.exception()
                    if exc is not None:
                        await self._handle_loop_exception(
                            name, exc, tasks, loop_factories
                        )
                        break
                    else:
                        # Loop completed without error — should never happen;
                        # restart to maintain supervision.
                        logger.warning(
                            "Loop %r completed unexpectedly — restarting", name
                        )
                        factory_fn = dict(loop_factories)[name]
                        tasks[name] = asyncio.create_task(
                            factory_fn(), name=f"hydraflow-{name}"
                        )
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            # #9911: cancelled loop bodies unwind without running their
            # subprocess cleanup when cancellation lands inside wait_for;
            # reap whatever the drained loops left behind.
            reap_all_tracked_processes()

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

    async def _do_implement_work(self) -> bool:
        """Work function for the implement loop."""
        did_work = False
        # After one poll cycle, release crash-recovered issues
        if self._recovered_issues:
            async with self._active_issues_lock:
                self._svc.implementer.active_issues.difference_update(
                    self._recovered_issues
                )
                self._recovered_issues.clear()
                self._sync_active_issue_numbers()
        while not self._stop_event.is_set():
            results, issues = await self._svc.implementer.run_batch()
            if not issues:
                break
            did_work = True
            await self._svc.implementer.post_impl_transcript_hooks(results)
            for result in results:
                self._session_issue_results[result.issue_number] = result.success
        return did_work

    async def _do_review_work(self) -> bool:
        """Work function for the review loop — continuous slot-filling pool.

        Instead of fetching a batch and waiting for all reviews to finish,
        this maintains a pool of up to ``max_reviewers`` concurrent tasks.
        As each review completes, the freed slot is immediately refilled
        from the queue so no capacity sits idle.
        """
        did_work = False
        pending: set[asyncio.Task[bool]] = set()
        max_slots = self._config.max_reviewers

        while not self._stop_event.is_set():
            # Fill empty slots from the queue
            free_slots = max_slots - len(pending)
            if free_slots > 0:
                new_issues = self._svc.store.get_reviewable(free_slots)
                for issue in new_issues:
                    task = asyncio.create_task(
                        self._review_single_issue(issue),
                        name=f"review-issue-{issue.id}",
                    )
                    pending.add(task)

            if not pending:
                break

            # Wait for at least one review to complete, then refill
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            batch_did_work = False
            for task in done:
                exc = task.exception()
                if exc is not None:
                    await handle_pool_worker_exception(
                        exc,
                        pending,
                        log=logger,
                        context="Review worker failed unexpectedly",
                    )
                elif task.result():
                    did_work = True
                    batch_did_work = True

            # When all completed tasks did no real work (e.g. PR not visible,
            # re-queued), pause briefly to avoid a hot spin loop.
            if not batch_did_work and not pending:
                break

        # Cancel stragglers on stop
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        return did_work

    async def _review_single_issue(self, issue: Task) -> bool:
        """Fetch PR and run review for a single issue, handling results inline.

        Returns ``True`` when a review actually ran, ``False`` when the
        issue was only re-queued (e.g. PR not visible yet).
        """
        try:
            if is_adr_issue_title(issue.title):
                await self._svc.reviewer.review_adrs([issue])
                return True

            # ``get_active_issues`` is orchestrator-only — not on IssueStorePort.
            active_in_store = set(
                cast("IssueStore", self._svc.store).get_active_issues().keys()
            )
            gh_issue = GitHubIssue.from_task(issue)
            prs, gh_issues = await self._svc.fetcher.fetch_reviewable_prs(
                active_in_store, prefetched_issues=[gh_issue]
            )
            if not prs:
                # PR not visible yet — usually propagation delay, but after a
                # restart mid-implement the PR may NOT EXIST and the issue
                # would otherwise sit review-labeled forever (#9815). Count
                # strikes; at the threshold, requeue with fresh budget
                # (bounded, then HITL) instead of waiting eternally.
                if await self._handle_review_orphan(issue):
                    return False
                await self._sleep_or_stop(min(self._config.poll_interval, 30))
                self._svc.store.enqueue_transition(issue, "review")
                return False
            self._state.clear_review_orphan_strikes(issue.id)

            review_results = await self._svc.reviewer.review_prs(
                prs, [i.to_task() for i in gh_issues]
            )
            await self._svc.reviewer.post_review_transcript_hooks(review_results)
            if any(r.merged for r in review_results):
                await asyncio.sleep(_POST_MERGE_DELAY)
                await self._svc.prs.pull_main()
            return True
        finally:
            release_batch_in_flight(self._svc.store, {issue.id})

    async def _handle_review_orphan(self, issue: Task) -> bool:
        """Requeue a review-labeled issue whose agent PR does not exist (#9815).

        Returns True when the issue was requeued (to ready) or escalated (to
        HITL) — the caller must NOT re-enqueue it to review. Returns False
        while strikes are below the threshold (normal PR-propagation wait) or
        when the feature is disabled (``review_orphan_max_requeues=0``).
        Every gh failure is fail-soft back to the legacy wait path.
        """
        if self._config.review_orphan_max_requeues <= 0:
            return False
        strikes = self._state.increment_review_orphan_strike(issue.id)
        if strikes < self._config.review_orphan_strike_threshold:
            return False

        self._state.clear_review_orphan_strikes(issue.id)
        requeues = self._state.increment_review_orphan_requeue(issue.id)
        try:
            if requeues > self._config.review_orphan_max_requeues:
                cause = (
                    f"review-labeled with no agent PR after "
                    f"{requeues - 1} orphan requeue(s) — needs a human"
                )
                self._state.set_hitl_cause(issue.id, cause)
                await self._svc.prs.swap_pipeline_labels(
                    issue.id, self._config.hitl_label[0]
                )
                await self._svc.prs.post_comment(
                    issue.id,
                    "## Review Orphan Escalation\n\n"
                    f"{cause}. Escalating to HITL (#9815).",
                )
                logger.warning(
                    "Issue #%d: review orphan exhausted %d requeues — HITL",
                    issue.id,
                    self._config.review_orphan_max_requeues,
                )
                return True

            self._state.reset_issue_attempts(issue.id)
            self._state.clear_diagnostic_state(issue.id)
            await self._svc.prs.swap_pipeline_labels(
                issue.id, self._config.ready_label[0]
            )
            await self._svc.prs.post_comment(
                issue.id,
                "## Review Orphan Requeue\n\n"
                "This issue was review-labeled with no open agent PR "
                "(interrupted implement, e.g. a factory restart). Attempt "
                f"counters reset; requeued to ready for a fresh build "
                f"(requeue {requeues}/"
                f"{self._config.review_orphan_max_requeues}, #9815).",
            )
            logger.info(
                "Issue #%d: review orphan requeued to ready (%d/%d)",
                issue.id,
                requeues,
                self._config.review_orphan_max_requeues,
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "Issue #%d: review orphan handling failed (%s) — keeping "
                "legacy review wait",
                issue.id,
                exc,
            )
            return False

    async def _sleep_or_stop(self, seconds: int | float) -> None:
        """Sleep for *seconds*, waking early if stop is requested."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

    def _loop_uses_gateway_transport(self, loop_name: str | None) -> bool:
        """Whether a core work loop's next spawn resolves through the gateway.

        The explicit role dial wins. A still-Claude role may also inherit the
        repo-wide gateway override. The fleet ratchet is included as a final
        fail-safe for live config objects changed after validation. Non-core
        maintenance loops are excluded because their one-shot seam does not
        participate in work-spawn credit failover.
        """
        if loop_name not in _PRIMARY_WORK_LOOP_TO_TOOL_FIELD:
            return False
        route_fields = _BACKEND_WORKER_LOOPS[loop_name]
        provider = getattr(self._config, route_fields[0])
        if provider == "gateway":
            return True
        if provider != "claude":
            return False
        tool = getattr(self._config, _PRIMARY_WORK_LOOP_TO_TOOL_FIELD[loop_name])
        if tool != "claude":
            return False
        return bool(
            self._config.repo_provider == "gateway"
            or self._config.gateway_fleet_ratchet_enabled
        )

    def _loop_providers(self, loop_names: Iterable[str]) -> dict[str, str]:
        """Map each loop name to the billing provider its LLM work routes to.

        Loops in ``_BACKEND_WORKER_LOOPS`` read their configured provider/model
        pair.  The model is required because ``gateway`` is a transport: Claude
        models bill Anthropic while ``glm-*`` models bill z.ai.  Every other
        loop runs on the Claude harness → ``"anthropic"``. Read from live config
        so an operator's dial change takes effect on the next pause."""
        providers: dict[str, str] = {}
        for name in loop_names:
            route_fields = _BACKEND_WORKER_LOOPS.get(name)
            if route_fields is None:
                providers[name] = PROVIDER_ANTHROPIC
            else:
                dial_field, model_field = route_fields
                dial = getattr(self._config, dial_field)
                configured_model = getattr(self._config, model_field)
                model = (
                    resolve_maintenance_model(
                        role_model=configured_model,
                        maintenance_model=self._config.maintenance_model,
                        background_model=self._config.background_model,
                    )
                    if dial_field == "maintenance_provider"
                    else configured_model or "haiku"
                )
                providers[name] = normalize_provider(
                    harness_billing_provider(dial, model)
                )
        return providers

    def _affected_loops(
        self, provider: str, loop_names: Iterable[str], source: str
    ) -> tuple[set[str], bool]:
        """Which loops a *provider* exhaustion must pause, + whether to terminate
        the shared Claude-harness runner pools.

        - Unknown provider (``normalize_provider`` changes it) → GLOBAL fallback:
          pause every loop and terminate the runner pools (today's behavior).
        - ``"anthropic"`` → pause every anthropic-routed loop (all but the
          surviving backend workers) and terminate the harness pools.
        - A backend (``"zai"``/``"kimi"``/``"openrouter"``) → pause only loops
          routed there (always including *source*, which demonstrably routes to
          it since it raised the signal) and leave the harness pools running."""
        names = list(loop_names)
        provider_map = self._loop_providers(names)
        if normalize_provider(provider) != provider:
            # Provider the registry doesn't recognize — fail safe to a global pause.
            return set(names), True
        affected = {n for n, p in provider_map.items() if p == provider}
        if provider != PROVIDER_ANTHROPIC and source in provider_map:
            affected.add(source)
        return affected, provider == PROVIDER_ANTHROPIC

    def _compute_resume_time(self, exc: CreditExhaustedError) -> datetime:
        """Compute the UTC datetime at which credit pause should end."""
        buffer = timedelta(minutes=self._config.credit_pause_buffer_minutes)
        now = datetime.now(UTC)
        if exc.resume_at is not None:
            return exc.resume_at + buffer
        return now + timedelta(hours=5) + buffer

    async def _cancel_all_loops_and_runners(
        self,
        tasks: dict[str, asyncio.Task[None]],
        affected: set[str] | None = None,
        *,
        terminate_runners: bool = True,
    ) -> None:
        """Cancel the *affected* loop tasks and (optionally) terminate the
        Claude-harness subprocess pools.

        *affected* ``None`` means every loop (the global / Anthropic pause).
        A backend-scoped pause (z.ai/kimi/openrouter) passes only the loops
        routed to that backend and ``terminate_runners=False`` so the shared
        harness runner pools — which bill against Anthropic and belong to the
        surviving loops — are left untouched (#9807)."""
        to_cancel = (
            tasks if affected is None else {n: tasks[n] for n in affected if n in tasks}
        )
        for task in to_cancel.values():
            task.cancel()
        await asyncio.gather(*to_cancel.values(), return_exceptions=True)
        if terminate_runners:
            self._svc.planners.terminate()
            self._svc.agents.terminate()
            self._svc.reviewers.terminate()
            self._svc.hitl_runner.terminate()
            reap_all_tracked_processes()

    async def _sleep_until_resume(self, resume_at: datetime) -> None:
        """Sleep until *resume_at* (interruptible by stop or credit-resume event)."""
        pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)
        sleep_task = asyncio.create_task(self._sleep_or_stop(pause_seconds))
        resume_task = asyncio.create_task(self._credit_resume_event.wait())
        try:
            await asyncio.wait(
                {sleep_task, resume_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (sleep_task, resume_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._credit_resume_event.clear()

    async def _pause_for_credits(
        self,
        exc: CreditExhaustedError,
        source: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> bool:
        """Pause all loops until API credits reset, then restart them.

        Uses ``asyncio.Lock`` to prevent multiple loops from racing into
        the pause logic simultaneously.

        Returns ``True`` when a pause is committed (or one is already active) —
        the crashed task will be recreated by the resume path — and ``False``
        when the probe refutes the signal as a false positive and no pause
        happens, so the caller must restart the crashed loop itself (#9924).
        """
        async with self._credit_pause_lock:
            # If another loop already triggered a pause, skip
            if (
                self._credits_paused_until is not None
                and self._credits_paused_until > datetime.now(UTC)
            ):
                return True

            # Which backend hit the limit (#9807). Default "anthropic" — the
            # Claude harness — so every legacy raise site stays global-scoped;
            # the one-shot backends (z.ai/kimi/openrouter) tag their own signal.
            provider = (
                getattr(exc, "provider", PROVIDER_ANTHROPIC) or PROVIDER_ANTHROPIC
            )

            # Origin gate (#10558): an AUTHORITATIVE signal came from the
            # subprocess's own termination — the CLI's stderr / a structured HTTP
            # 402/429/quota body — and is ground truth. Only a signal scanned from
            # agent stdout PROSE (a diagnostic/reviewer run quoting a prior cap —
            # the #9895 CREDIT_PROSE_SCAN class) needs the probe. The auth/
            # availability probe structurally CANNOT detect a *weekly*-limit
            # exhaustion (the key stays valid, so the probe passes), so routing a
            # genuine weekly signal through it discarded it as a false positive and
            # the factory never paused — loops then crash-thrashed against the
            # exhausted budget. Corroborate prose-only signals; pause directly on
            # authoritative ones. Defaults to the conservative "corroborate"
            # stance so an untagged/unknown signal keeps the legacy probe gate.
            authoritative = getattr(exc, "authoritative", False)

            # Corroborate the text-detected signal with a live API probe before
            # committing a GLOBAL pause. ``is_credit_exhaustion`` matches
            # credit-error PROSE, so a diagnostic/reviewer run that merely quotes
            # a prior cap in its analysis would otherwise trigger a multi-hour
            # false global pause (#9807). The probe is ground truth: it returns
            # False only when the API itself confirms exhaustion, and fails open
            # (True on no-key/network error) so a flaky probe delays a real pause
            # by at most one detection cycle rather than masking it. Kill-switch:
            # ``credit_pause_require_probe=False`` reverts to pause-on-text.
            # ``and`` short-circuits: with the kill-switch off, the probe is
            # never called (pause-on-text, the legacy behavior).
            # Throttle repeat false positives from the same source (#9888):
            # within the cooldown, skip the probe AND the banner — log-only.
            # Six suppression banners landed in 3ms before this guard.
            fp_last = self._credit_fp_last.get(source)
            cooldown = float(self._config.credit_fp_suppress_cooldown_seconds)
            if (
                not authoritative
                and self._config.credit_pause_require_probe
                and fp_last is not None
                and (datetime.now(UTC) - fp_last).total_seconds() < cooldown
            ):
                logger.debug(
                    "Credit FP from %r within %.0fs cooldown — suppressed (log-only)",
                    source,
                    cooldown,
                )
                return False

            # Probe the AFFECTED backend, not always Anthropic (#9807): a z.ai
            # 429 is corroborated against z.ai's endpoint, a Claude cap against
            # Anthropic. Endpoint (base_url/api_key) resolves from the provider
            # registry; anthropic → ("","") which the probe ignores.
            probe_base_url, probe_api_key = backend_probe_endpoint(
                provider, self._config
            )
            if (
                not authoritative
                and self._config.credit_pause_require_probe
                and await probe_credit_availability(
                    provider, base_url=probe_base_url, api_key=probe_api_key
                )
            ):
                self._credit_fp_last[source] = datetime.now(UTC)
                logger.warning(
                    "Credit-exhaustion signal from %r (provider=%s) NOT "
                    "corroborated by live API probe — treating as a false "
                    "positive (likely quoted credit-error prose); not pausing.",
                    source,
                    provider,
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "message": (
                                "Credit signal not corroborated by API probe "
                                "— ignoring as a false positive."
                            ),
                            "source": source,
                            "provider": provider,
                            # Benign: a false positive was suppressed, nothing
                            # paused. Render yellow, not the red critical banner.
                            "severity": "warning",
                        },
                    )
                )
                return False

            resume_at = self._compute_resume_time(exc)
            self._credits_paused_until = resume_at
            self._credit_paused_provider = provider
            pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)

            # Scope the pause to the loops routed to this backend. Anthropic (or
            # an unrecognized provider) still pauses the whole factory except the
            # surviving backend workers; a z.ai/kimi cap pauses only its own
            # loops and leaves Claude work running (#9807).
            affected, terminate_runners = self._affected_loops(
                provider, tasks.keys(), source
            )
            scope = "all loops" if terminate_runners else f"{provider} loops"

            logger.warning(
                "Credit limit reached (detected in %r, provider=%s). "
                "Pausing %s until %s (%.0f minutes).",
                source,
                provider,
                scope,
                resume_at.isoformat(),
                pause_seconds / 60,
            )

            data: SystemAlertPayload = {
                "message": f"Credit limit reached ({provider}). Pausing {scope}.",
                "source": source,
                "provider": provider,
                "resume_at": resume_at.isoformat(),
            }
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data=data,
                )
            )

            await self._cancel_all_loops_and_runners(
                tasks, affected, terminate_runners=terminate_runners
            )

        await self._sleep_until_resume(resume_at)

        if self._stop_event.is_set():
            self._credits_paused_until = None
            self._credit_paused_provider = None
            self._credit_resume_event.clear()
            return True

        await self._resume_loops_after_credit_pause(
            tasks, loop_factories, source, affected
        )
        return True

    async def _resume_loops_after_credit_pause(
        self,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        source: str,
        affected: set[str] | None = None,
    ) -> None:
        """Clear pause state and restart the loops paused for this credit pause.

        *affected* ``None`` restarts every loop (global/legacy). A scoped pause
        passes the same set it cancelled so only those loops are recreated —
        the surviving backend/harness loops were never touched (#9807)."""
        if self._stop_event.is_set():
            # Stop landed during the pause: clear the pause state but do NOT
            # recreate any loop. ``_pause_for_credits`` already short-circuits
            # to this outcome before calling us; this guard also fail-safes any
            # future caller so a credit pause that ends after stop never leaks a
            # live loop past the shutdown drain and wedges "stopping" (#10569).
            self._credits_paused_until = None
            self._credit_paused_provider = None
            self._credit_resume_event.clear()
            return
        provider = self._credit_paused_provider
        self._credits_paused_until = None
        self._credit_paused_provider = None
        self._credit_resume_event.clear()
        scope = "all loops" if affected is None else f"{len(affected)} loop(s)"
        logger.info("Credit pause ended — restarting %s", scope)
        data: SystemAlertPayload = {
            "message": "Credit pause ended. Resuming loops.",
            "source": source,
        }
        if provider is not None:
            data["provider"] = provider
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data=data,
            )
        )
        for loop_name, factory in loop_factories:
            if affected is not None and loop_name not in affected:
                continue
            tasks[loop_name] = asyncio.create_task(
                factory(), name=f"hydraflow-{loop_name}"
            )

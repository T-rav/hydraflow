"""Main orchestrator loop — plan, implement, review, cleanup, repeat.

The class is assembled from cohesive mixins (god-class decomposition, Refs
#11547) but keeps ONE identity here: ``from orchestrator import
HydraFlowOrchestrator`` and every ``patch("orchestrator.HydraFlowOrchestrator.
<method>")`` target resolve exactly as before. This module keeps construction
and the read-only accessors the dashboard binds to; the moved surfaces live in
``orchestrator_lifecycle`` / ``_restart`` / ``_credits`` / ``_loops`` /
``_work`` / ``_hitl`` / ``_bg_workers`` / ``_stats``, with the shared
module-level constants in ``orchestrator_common``.

The ADR-0001 concurrent-loop shape itself stays here: ``run``, the
``loop_factories`` list and the ``asyncio.gather`` supervisor are the
orchestrator's defining responsibility and the thing the P6.1 audit probe
and the loop-wiring guards read out of this file.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from bg_worker_manager import BGWorkerManager
from config import HydraFlowConfig
from event_loop_watchdog import build_event_loop_watchdog
from events import EventBus
from hitl_controller import HITLController
from models import (
    SessionLog,
)
from orchestrator_bg_workers import OrchestratorBGWorkersMixin
from orchestrator_common import (
    _AUTH_TRANSIENT_RESTART_DELAY_S,
    _BACKEND_WORKER_LOOPS,
    _POST_MERGE_DELAY,
    _PRIMARY_WORK_LOOP_TO_TOOL_FIELD,
    _log_deferred_task_failure,
)
from orchestrator_credits import OrchestratorCreditsMixin
from orchestrator_hitl import OrchestratorHITLMixin
from orchestrator_lifecycle import OrchestratorLifecycleMixin
from orchestrator_loops import OrchestratorLoopsMixin
from orchestrator_restart import OrchestratorRestartMixin
from orchestrator_stats import OrchestratorStatsMixin
from orchestrator_work import OrchestratorWorkMixin
from runner_utils import reap_all_tracked_processes
from service_registry import (
    ServiceRegistry,
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)
from state import StateTracker
from state_restorer import StateRestorer

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

# Re-exported for back-compat: these module-level names lived here before the
# decomposition, so ``from orchestrator import _BACKEND_WORKER_LOOPS`` (and the
# ADR-0110 citation of ``orchestrator.py:_BACKEND_WORKER_LOOPS``) keep working.
__all__ = [
    "HydraFlowOrchestrator",
    "OrchestratorBGWorkersMixin",
    "OrchestratorCreditsMixin",
    "OrchestratorHITLMixin",
    "OrchestratorLifecycleMixin",
    "OrchestratorLoopsMixin",
    "OrchestratorStatsMixin",
    "OrchestratorRestartMixin",
    "OrchestratorWorkMixin",
    "_AUTH_TRANSIENT_RESTART_DELAY_S",
    "_BACKEND_WORKER_LOOPS",
    "_POST_MERGE_DELAY",
    "_PRIMARY_WORK_LOOP_TO_TOOL_FIELD",
    "_log_deferred_task_failure",
]


class HydraFlowOrchestrator(
    OrchestratorBGWorkersMixin,
    OrchestratorCreditsMixin,
    OrchestratorHITLMixin,
    OrchestratorLifecycleMixin,
    OrchestratorLoopsMixin,
    OrchestratorStatsMixin,
    OrchestratorRestartMixin,
    OrchestratorWorkMixin,
):
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
            "charter_drift_caretaker": svc.charter_drift_caretaker_loop,
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

    @property
    def current_session_id(self) -> str | None:
        """Return the active session ID, or None."""
        return self._current_session.id if self._current_session else None

    # ------------------------------------------------------------------
    # ADR-0001 concurrent-loop shape. Deliberately kept in this module: the
    # loop-factory list and the gather that supervises it are what P6.1 and
    # the loop-wiring guards read out of ``orchestrator.py``, and they are
    # the orchestrator's defining responsibility.
    # ------------------------------------------------------------------

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
                "charter_drift_caretaker",
                self._svc.charter_drift_caretaker_loop.run,
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

"""Service registry and factory for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from acceptance_criteria import AcceptanceCriteriaGenerator
from adr_reviewer import ADRCouncilReviewer
from adr_reviewer_loop import ADRReviewerLoop
from agent import AgentRunner
from base_background_loop import LoopDeps
from baseline_policy import BaselinePolicy
from config import HydraFlowConfig
from crate_manager import CrateManager
from docker_runner import get_docker_runner
from epic import EpicCompletionChecker, EpicManager
from epic_monitor_loop import EpicMonitorLoop
from epic_sweeper_loop import EpicSweeperLoop
from events import EventBus
from execution import SubprocessRunner
from harness_insights import HarnessInsightStore
from hitl_phase import HITLPhase
from hitl_runner import HITLRunner
from implement_phase import ImplementPhase
from issue_fetcher import GitHubTaskFetcher, IssueFetcher
from issue_store import IssueStore
from manifest import ProjectManifestManager
from manifest_issue_syncer import ManifestIssueSyncer
from manifest_refresh_loop import ManifestRefreshLoop
from memory import MemorySyncWorker
from memory_sync_loop import MemorySyncLoop
from merge_conflict_resolver import MergeConflictResolver
from metrics_sync_loop import MetricsSyncLoop
from models import StatusCallback
from plan_phase import PlanPhase
from planner import PlannerRunner
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager
from pr_unsticker import PRUnsticker
from pr_unsticker_loop import PRUnstickerLoop
from report_issue_loop import ReportIssueLoop
from research_runner import ResearchRunner
from retrospective import RetrospectiveCollector
from review_phase import ReviewPhase
from reviewer import ReviewRunner
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from triage import TriageRunner
from triage_phase import TriagePhase
from troubleshooting_store import TroubleshootingPatternStore
from verification_judge import VerificationJudge
from verify_monitor_loop import VerifyMonitorLoop
from workspace import WorkspaceManager
from workspace_gc_loop import WorkspaceGCLoop

if TYPE_CHECKING:
    from metrics_manager import MetricsManager


@dataclass
class ServiceRegistry:
    """Holds all service instances for the orchestrator."""

    # Core infrastructure
    worktrees: WorkspaceManager
    subprocess_runner: SubprocessRunner
    agents: AgentRunner
    planners: PlannerRunner
    prs: PRManager
    reviewers: ReviewRunner
    hitl_runner: HITLRunner
    triage: TriageRunner
    summarizer: TranscriptSummarizer

    # Data layer
    fetcher: IssueFetcher
    store: IssueStore
    crate_manager: CrateManager

    # Phase coordinators
    triager: TriagePhase
    planner_phase: PlanPhase
    hitl_phase: HITLPhase
    implementer: ImplementPhase
    reviewer: ReviewPhase

    # Background workers and support
    run_recorder: RunRecorder
    metrics_manager: MetricsManager
    pr_unsticker: PRUnsticker
    memory_sync: MemorySyncWorker
    retrospective: RetrospectiveCollector
    ac_generator: AcceptanceCriteriaGenerator
    verification_judge: VerificationJudge
    epic_checker: EpicCompletionChecker
    epic_manager: EpicManager

    # Background loops
    memory_sync_bg: MemorySyncLoop
    metrics_sync_bg: MetricsSyncLoop
    pr_unsticker_loop: PRUnstickerLoop
    manifest_refresh_loop: ManifestRefreshLoop
    report_issue_loop: ReportIssueLoop
    epic_monitor_loop: EpicMonitorLoop
    epic_sweeper_loop: EpicSweeperLoop
    verify_monitor_loop: VerifyMonitorLoop
    worktree_gc_loop: WorkspaceGCLoop
    runs_gc_loop: RunsGCLoop
    adr_reviewer_loop: ADRReviewerLoop


@dataclass
class OrchestratorCallbacks:
    """Callbacks from the orchestrator needed during service construction."""

    sync_active_issue_numbers: Callable[[], None]
    update_bg_worker_status: StatusCallback
    is_bg_worker_enabled: Callable[[str], bool]
    sleep_or_stop: Callable[[int | float], Coroutine[Any, Any, None]]
    get_bg_worker_interval: Callable[[str], int]


@dataclass
class _CoreRunners:
    """Intermediate bundle of core runners built during service construction."""

    worktrees: WorkspaceManager
    subprocess_runner: SubprocessRunner
    agents: AgentRunner
    planners: PlannerRunner
    researcher: ResearchRunner
    prs: PRManager
    manifest_syncer: ManifestIssueSyncer
    reviewers: ReviewRunner
    hitl_runner: HITLRunner
    triage: TriageRunner
    summarizer: TranscriptSummarizer


@dataclass
class _DataLayer:
    """Intermediate bundle of data-layer services."""

    fetcher: IssueFetcher
    store: IssueStore
    crate_manager: CrateManager
    harness_insights: HarnessInsightStore
    troubleshooting_store: TroubleshootingPatternStore
    epic_checker: EpicCompletionChecker
    epic_manager: EpicManager


def _build_core_runners(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
) -> _CoreRunners:
    """Build core runner services (agents, planners, PR manager, etc.)."""
    worktrees = WorkspaceManager(config)
    subprocess_runner = get_docker_runner(config)
    agents = AgentRunner(config, event_bus, runner=subprocess_runner)
    planners = PlannerRunner(config, event_bus, runner=subprocess_runner)
    researcher = ResearchRunner(config, event_bus, runner=subprocess_runner)
    prs = PRManager(config, event_bus)
    manifest_syncer = ManifestIssueSyncer(config, state, prs)
    reviewers = ReviewRunner(config, event_bus, runner=subprocess_runner)
    hitl_runner = HITLRunner(config, event_bus, runner=subprocess_runner)
    triage = TriageRunner(config, event_bus, runner=subprocess_runner)
    summarizer = TranscriptSummarizer(
        config, prs, event_bus, state, runner=subprocess_runner
    )
    return _CoreRunners(
        worktrees=worktrees,
        subprocess_runner=subprocess_runner,
        agents=agents,
        planners=planners,
        researcher=researcher,
        prs=prs,
        manifest_syncer=manifest_syncer,
        reviewers=reviewers,
        hitl_runner=hitl_runner,
        triage=triage,
        summarizer=summarizer,
    )


def _build_data_layer(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    runners: _CoreRunners,
) -> _DataLayer:
    """Build data-layer services (fetcher, store, epics, insight stores)."""
    fetcher = IssueFetcher(config)
    store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)
    crate_manager = CrateManager(config, state, runners.prs, event_bus)
    store.set_crate_manager(crate_manager)
    harness_insights = HarnessInsightStore(config.data_path("memory"))
    troubleshooting_store = TroubleshootingPatternStore(config.data_path("memory"))
    epic_checker = EpicCompletionChecker(config, runners.prs, fetcher, state=state)
    epic_manager = EpicManager(config, state, runners.prs, fetcher, event_bus)
    return _DataLayer(
        fetcher=fetcher,
        store=store,
        crate_manager=crate_manager,
        harness_insights=harness_insights,
        troubleshooting_store=troubleshooting_store,
        epic_checker=epic_checker,
        epic_manager=epic_manager,
    )


def _build_phase_coordinators(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: OrchestratorCallbacks,
    runners: _CoreRunners,
    data: _DataLayer,
) -> tuple[
    TriagePhase,
    PlanPhase,
    HITLPhase,
    RunRecorder,
    ImplementPhase,
    MetricsManager,
    PRUnsticker,
    MemorySyncWorker,
    RetrospectiveCollector,
    AcceptanceCriteriaGenerator,
    VerificationJudge,
    ReviewPhase,
]:
    """Build phase coordinators and their support services."""
    triager = TriagePhase(
        config,
        state,
        data.store,
        runners.triage,
        runners.prs,
        event_bus,
        stop_event,
        epic_manager=data.epic_manager,
    )
    planner_phase = PlanPhase(
        config,
        state,
        data.store,
        runners.planners,
        runners.prs,
        event_bus,
        stop_event,
        transcript_summarizer=runners.summarizer,
        harness_insights=data.harness_insights,
        epic_manager=data.epic_manager,
        research_runner=runners.researcher,
    )
    hitl_phase = HITLPhase(
        config,
        state,
        data.store,
        data.fetcher,
        runners.worktrees,
        runners.hitl_runner,
        runners.prs,
        event_bus,
        stop_event,
        active_issues_cb=callbacks.sync_active_issue_numbers,
    )
    run_recorder = RunRecorder(config)
    implementer = ImplementPhase(
        config,
        state,
        runners.worktrees,
        runners.agents,
        runners.prs,
        data.store,
        stop_event,
        run_recorder=run_recorder,
        harness_insights=data.harness_insights,
    )

    from metrics_manager import MetricsManager

    metrics_manager = MetricsManager(config, state, runners.prs, event_bus)
    conflict_resolver = MergeConflictResolver(
        config=config,
        worktrees=runners.worktrees,
        agents=runners.agents,
        prs=runners.prs,
        event_bus=event_bus,
        state=state,
        summarizer=runners.summarizer,
    )
    pr_unsticker = PRUnsticker(
        config,
        state,
        event_bus,
        runners.prs,
        runners.agents,
        runners.worktrees,
        data.fetcher,
        hitl_runner=runners.hitl_runner,
        stop_event=stop_event,
        resolver=conflict_resolver,
        troubleshooting_store=data.troubleshooting_store,
    )
    memory_sync = MemorySyncWorker(
        config,
        state,
        event_bus,
        runner=runners.subprocess_runner,
        prs=runners.prs,
        manifest_syncer=runners.manifest_syncer,
    )
    retrospective = RetrospectiveCollector(config, state, runners.prs)
    ac_generator = AcceptanceCriteriaGenerator(
        config, runners.prs, event_bus, runner=runners.subprocess_runner
    )
    verification_judge = VerificationJudge(
        config, event_bus, runner=runners.subprocess_runner
    )
    baseline_policy = BaselinePolicy(
        config=config,
        state=state,
        event_bus=event_bus,
    )
    post_merge_handler = PostMergeHandler(
        config=config,
        state=state,
        prs=runners.prs,
        event_bus=event_bus,
        ac_generator=ac_generator,
        retrospective=retrospective,
        verification_judge=verification_judge,
        epic_checker=data.epic_checker,
        update_bg_worker_status=callbacks.update_bg_worker_status,
        epic_manager=data.epic_manager,
    )
    reviewer = ReviewPhase(
        config,
        state,
        runners.worktrees,
        runners.reviewers,
        runners.prs,
        stop_event,
        data.store,
        event_bus=event_bus,
        harness_insights=data.harness_insights,
        conflict_resolver=conflict_resolver,
        post_merge=post_merge_handler,
        update_bg_worker_status=callbacks.update_bg_worker_status,
        baseline_policy=baseline_policy,
    )
    return (
        triager,
        planner_phase,
        hitl_phase,
        run_recorder,
        implementer,
        metrics_manager,
        pr_unsticker,
        memory_sync,
        retrospective,
        ac_generator,
        verification_judge,
        reviewer,
    )


def _build_background_loops(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    callbacks: OrchestratorCallbacks,
    stop_event: asyncio.Event,
    runners: _CoreRunners,
    data: _DataLayer,
    *,
    run_recorder: RunRecorder,
    metrics_manager: MetricsManager,
    pr_unsticker: PRUnsticker,
    memory_sync: MemorySyncWorker,
) -> tuple[
    MemorySyncLoop,
    MetricsSyncLoop,
    PRUnstickerLoop,
    ManifestRefreshLoop,
    ReportIssueLoop,
    EpicMonitorLoop,
    EpicSweeperLoop,
    VerifyMonitorLoop,
    WorkspaceGCLoop,
    RunsGCLoop,
    ADRReviewerLoop,
]:
    """Build all background polling loops."""
    loop_deps = LoopDeps(
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_bg_worker_status,
        enabled_cb=callbacks.is_bg_worker_enabled,
        sleep_fn=callbacks.sleep_or_stop,
        interval_cb=callbacks.get_bg_worker_interval,
    )
    memory_sync_bg = MemorySyncLoop(config, data.fetcher, memory_sync, deps=loop_deps)
    metrics_sync_bg = MetricsSyncLoop(
        config, data.store, metrics_manager, deps=loop_deps
    )
    pr_unsticker_loop = PRUnstickerLoop(
        config, pr_unsticker, runners.prs, deps=loop_deps
    )
    manifest_manager = ProjectManifestManager(config)
    manifest_refresh_loop = ManifestRefreshLoop(
        config,
        manifest_manager,
        state,
        deps=loop_deps,
        manifest_syncer=runners.manifest_syncer,
    )
    report_issue_loop = ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=runners.prs,
        deps=loop_deps,
        runner=runners.subprocess_runner,
    )
    epic_monitor_loop = EpicMonitorLoop(
        config=config, epic_manager=data.epic_manager, deps=loop_deps
    )
    epic_sweeper_loop = EpicSweeperLoop(
        config=config,
        fetcher=data.fetcher,
        prs=runners.prs,
        state=state,
        deps=loop_deps,
    )
    verify_monitor_loop = VerifyMonitorLoop(
        config=config,
        fetcher=data.fetcher,
        state=state,
        deps=loop_deps,
    )
    worktree_gc_loop = WorkspaceGCLoop(
        config=config,
        worktrees=runners.worktrees,
        prs=runners.prs,
        state=state,
        deps=loop_deps,
        is_in_pipeline_cb=data.store.is_in_pipeline,
    )
    runs_gc_loop = RunsGCLoop(config=config, run_recorder=run_recorder, deps=loop_deps)
    adr_reviewer = ADRCouncilReviewer(
        config, event_bus, runners.prs, runners.subprocess_runner
    )
    adr_reviewer_loop = ADRReviewerLoop(
        config=config, adr_reviewer=adr_reviewer, deps=loop_deps
    )
    return (
        memory_sync_bg,
        metrics_sync_bg,
        pr_unsticker_loop,
        manifest_refresh_loop,
        report_issue_loop,
        epic_monitor_loop,
        epic_sweeper_loop,
        verify_monitor_loop,
        worktree_gc_loop,
        runs_gc_loop,
        adr_reviewer_loop,
    )


def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: OrchestratorCallbacks,
) -> ServiceRegistry:
    """Create all services wired together.

    Construction is split into four phases: core runners, data layer,
    phase coordinators, and background loops.
    """
    runners = _build_core_runners(config, event_bus, state)
    data = _build_data_layer(config, event_bus, state, runners)

    (
        triager,
        planner_phase,
        hitl_phase,
        run_recorder,
        implementer,
        metrics_manager,
        pr_unsticker,
        memory_sync,
        retrospective,
        ac_generator,
        verification_judge,
        reviewer,
    ) = _build_phase_coordinators(
        config, event_bus, state, stop_event, callbacks, runners, data
    )

    (
        memory_sync_bg,
        metrics_sync_bg,
        pr_unsticker_loop,
        manifest_refresh_loop,
        report_issue_loop,
        epic_monitor_loop,
        epic_sweeper_loop,
        verify_monitor_loop,
        worktree_gc_loop,
        runs_gc_loop,
        adr_reviewer_loop,
    ) = _build_background_loops(
        config,
        event_bus,
        state,
        callbacks,
        stop_event,
        runners,
        data,
        run_recorder=run_recorder,
        metrics_manager=metrics_manager,
        pr_unsticker=pr_unsticker,
        memory_sync=memory_sync,
    )

    return ServiceRegistry(
        worktrees=runners.worktrees,
        subprocess_runner=runners.subprocess_runner,
        agents=runners.agents,
        planners=runners.planners,
        prs=runners.prs,
        reviewers=runners.reviewers,
        hitl_runner=runners.hitl_runner,
        triage=runners.triage,
        summarizer=runners.summarizer,
        fetcher=data.fetcher,
        store=data.store,
        crate_manager=data.crate_manager,
        triager=triager,
        planner_phase=planner_phase,
        hitl_phase=hitl_phase,
        implementer=implementer,
        reviewer=reviewer,
        run_recorder=run_recorder,
        metrics_manager=metrics_manager,
        pr_unsticker=pr_unsticker,
        memory_sync=memory_sync,
        retrospective=retrospective,
        ac_generator=ac_generator,
        verification_judge=verification_judge,
        epic_checker=data.epic_checker,
        epic_manager=data.epic_manager,
        memory_sync_bg=memory_sync_bg,
        metrics_sync_bg=metrics_sync_bg,
        pr_unsticker_loop=pr_unsticker_loop,
        manifest_refresh_loop=manifest_refresh_loop,
        report_issue_loop=report_issue_loop,
        epic_monitor_loop=epic_monitor_loop,
        epic_sweeper_loop=epic_sweeper_loop,
        verify_monitor_loop=verify_monitor_loop,
        worktree_gc_loop=worktree_gc_loop,
        runs_gc_loop=runs_gc_loop,
        adr_reviewer_loop=adr_reviewer_loop,
    )

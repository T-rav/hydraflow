"""Plan phase — run planning agents on issues and post results.

The class is assembled from cohesive mixins (god-class decomposition, Refs
#11547) but keeps ONE identity here: ``from plan_phase import PlanPhase`` and
every ``patch.object(PlanPhase, "<method>")`` target resolve exactly as before.
This module keeps construction and the queue-draining entry points; the moved
surfaces live in ``plan_phase_adversarial`` / ``_tiering`` / ``_prepass`` /
``_records`` / ``_disposition`` / ``_flow`` / ``_epic``, alongside the
pre-existing ``plan_phase_wiki_ingest`` (#10840), with the shared module-level
constants in ``plan_phase_common``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import plan_phase_wiki_ingest
from adversarial_agents import AgentLike
from config import HydraFlowConfig
from events import EventBus
from harness_insights import HarnessInsightStore
from models import (
    PipelineStage,
    PlanResult,
    Task,
)
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    release_batch_in_flight,
    run_refilling_pool,
)
from plan_phase_adversarial import PlanAdversarialMixin
from plan_phase_common import (
    _MIN_ISSUE_BODY_CHARS,
    _PLAN_VERDICT_MAP,
    _PRIORITY_LABELS,
    _flow_stopped,
)
from plan_phase_disposition import PlanDispositionMixin
from plan_phase_epic import PlanEpicMixin
from plan_phase_flow import PlanFlowMixin
from plan_phase_prepass import PlanPrepassMixin
from plan_phase_records import PlanRecordsMixin
from plan_phase_tiering import PlanTieringMixin
from plan_phase_wiki_ingest import PlanWikiIngestMixin
from planner import PlannerRunner
from repo_wiki import RepoWikiStore
from research_runner import ResearchRunner
from state import StateTracker
from task_source import TaskTransitioner
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from beads_manager import BeadsManager
    from discover_runner import DiscoverRunner
    from epic import EpicManager
    from issue_cache import IssueCache
    from plan_reviewer import PlanReviewer
    from plan_touchpoint_expander import PlanTouchpointExpander
    from ports import IssueStorePort, PRPort
    from shape_runner import ShapeRunner
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("hydraflow.plan_phase")


# Re-export (god-file decomposition, #10840): the wiki-ingest cluster moved
# verbatim to ``plan_phase_wiki_ingest`` — this keeps the historical
# ``from plan_phase import _run_fallback_ingest_plan`` seam working.
_run_fallback_ingest_plan = plan_phase_wiki_ingest._run_fallback_ingest_plan

# Re-exported for back-compat: these module-level names lived here before the
# decomposition, so ``from plan_phase import _PRIORITY_LABELS`` keeps working.
__all__ = [
    "PlanAdversarialMixin",
    "PlanDispositionMixin",
    "PlanEpicMixin",
    "PlanFlowMixin",
    "PlanPhase",
    "PlanPrepassMixin",
    "PlanRecordsMixin",
    "PlanTieringMixin",
    "_MIN_ISSUE_BODY_CHARS",
    "_PLAN_VERDICT_MAP",
    "_PRIORITY_LABELS",
    "_flow_stopped",
    "_run_fallback_ingest_plan",
]


class PlanPhase(
    PlanAdversarialMixin,
    PlanDispositionMixin,
    PlanEpicMixin,
    PlanFlowMixin,
    PlanPrepassMixin,
    PlanRecordsMixin,
    PlanTieringMixin,
    PlanWikiIngestMixin,
):
    """Runs planning agents on issues and posts results."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStorePort,
        planners: PlannerRunner,
        prs: PRPort,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        transcript_summarizer: TranscriptSummarizer | None = None,
        harness_insights: HarnessInsightStore | None = None,
        epic_manager: EpicManager | None = None,
        research_runner: ResearchRunner | None = None,
        beads_manager: BeadsManager | None = None,
        wiki_store: RepoWikiStore | None = None,
        wiki_compiler: WikiCompiler | None = None,
        issue_cache: IssueCache | None = None,
        plan_reviewer: PlanReviewer | None = None,
        touchpoint_expander: PlanTouchpointExpander | None = None,
        discover_runner: DiscoverRunner | None = None,
        shape_runner: ShapeRunner | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._planners = planners
        # Shared across every ``plan_single_issue`` call so repeated single-item
        # planning still honours ``max_planners`` (#11535). Built lazily: a
        # semaphore per call would cap nothing.
        self._solo_semaphore: asyncio.Semaphore | None = None
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._summarizer = transcript_summarizer
        self._harness_insights = harness_insights
        self._epic_manager = epic_manager
        self._research_runner = research_runner
        self._beads_manager = beads_manager
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._issue_cache = issue_cache
        self._plan_reviewer = plan_reviewer
        # ADR-0107: the discover/shape engines (DiscoverRunner / ShapeRunner),
        # reused as on-demand helpers the planner's decision gate invokes
        # (_should_discover_helper / _should_shape_helper) instead of them
        # running as standalone pipeline phases. Optional — when None (e.g.
        # tests that build PlanPhase directly without the factory), the gates
        # always return False and the planner plans without a research pre-pass.
        self._discover_runner = discover_runner
        self._shape_runner = shape_runner
        # Touchpoint expander (ADR-0063 W3b). Dispatched on the FIRST
        # PlanReviewer blocking-finding failure to enrich the next
        # review pass with cross-referenced ADRs, recent PR conflict
        # history, and current wiki entries for the touched modules.
        # Optional — when None, the existing route-back path runs
        # unchanged (backward-compat).
        self._touchpoint_expander = touchpoint_expander
        # Earlier-adversarial pipeline agents (ADR-pending). Optional —
        # the factory wires them in when feature-enabled; legacy paths
        # leave them None and the adversarial stages are skipped. See
        # ``attach_adversarial_agents`` for the production entry point.
        self._surfacer_agent: AgentLike | None = None
        self._council_agents: dict[str, AgentLike] | None = None
        self._spec_ac_agent: AgentLike | None = None
        self._spec_judge_agent: AgentLike | None = None
        self._adversarial_budget: int = 3
        self._suggest_memory = MemorySuggester(config)
        self._escalator = PipelineEscalator(
            state,
            prs,
            store,
            harness_insights,
            origin_label=config.planner_label[0],
            hitl_label=config.hitl_label[0],
            diagnose_label=config.diagnose_label[0],
            stage=PipelineStage.PLAN,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def plan_single_issue(
        self, issue: Task, *, semaphore: asyncio.Semaphore | None = None
    ) -> PlanResult:
        """Plan exactly *issue*, with no queue drain and no refilling pool (#11535).

        The explicit single-item entry point ``issue_controller`` scheduling
        needs. ``plan_issues`` is a *scheduler* — it drains the plan queue and
        decides how many issues to work — so a driver calling it would hand back
        the very decision it exists to own. This runs the same per-issue
        pipeline (``_plan_one``: prepass → surface → draft → council → route →
        records → gate → ready) under the same semaphore, sentry span and store
        lifecycle, so the planner's contract, prompts and output markers are
        untouched and shared by both schedulers.

        The planner-concurrency cap is preserved: callers that make repeated
        single-item calls pass the *same* semaphore, and the default is a
        process-lifetime one sized from ``max_planners`` so an omitted argument
        still throttles rather than silently uncapping the stage.
        """
        return await self._plan_one(
            0, issue, semaphore or self._single_item_semaphore()
        )

    def _single_item_semaphore(self) -> asyncio.Semaphore:
        """Shared ``max_planners`` semaphore for single-item planning.

        Built once and reused, because a fresh semaphore per call would cap
        nothing at all.
        """
        if self._solo_semaphore is None:
            self._solo_semaphore = asyncio.Semaphore(self._config.max_planners)
        return self._solo_semaphore

    async def plan_issues(self) -> list[PlanResult]:
        """Run planning agents on issues from the plan queue.

        Uses a slot-filling pool so new issues are picked up as soon
        as a planner slot frees, rather than waiting for the full batch.
        Epic children are still grouped and planned together when
        ``epic_group_planning`` is enabled.
        """
        semaphore = asyncio.Semaphore(self._config.max_planners)

        # If epic grouping is enabled, drain a batch first to identify
        # epic children, then plan them as groups.
        epic_results: list[PlanResult] = []
        handled_epic_children: set[int] = set()
        if self._config.epic_group_planning:
            batch = self._store.get_plannable(2 * self._config.max_planners)
            if batch:
                epic_groups, standalone = self._group_by_epic(batch)
                handled_epic_children = {
                    child.id for children in epic_groups.values() for child in children
                }
                # Re-queue standalone issues for the pool below
                for issue in standalone:
                    self._store.enqueue_transition(issue, "plan")
                release_batch_in_flight(self._store, {i.id for i in standalone})

                for epic_number, children in epic_groups.items():
                    if self._stop_event.is_set():
                        break
                    try:
                        results = await self._plan_epic_group(
                            epic_number, children, semaphore
                        )
                        epic_results.extend(results)
                        if self._epic_manager is not None:
                            for r in results:
                                if r.success and r.plan:
                                    await self._epic_manager.on_child_planned(
                                        epic_number, r.issue_number
                                    )
                    finally:
                        release_batch_in_flight(
                            self._store,
                            {c.id for c in children},
                            expected_stage="plan",
                        )

        async def _plan_worker(idx: int, issue: Task) -> PlanResult:
            try:
                return await self._plan_one(idx, issue, semaphore)
            finally:
                release_batch_in_flight(self._store, {issue.id})

        def _supply_standalone() -> list[Task]:
            """Exclude cohort children already handled by this plan cycle."""
            while candidates := self._store.get_plannable(1):
                candidate = candidates[0]
                if candidate.id not in handled_epic_children:
                    return candidates
                # A fail-closed gap replan may leave the child's original PLAN
                # queue entry for the next reconciled poll. Consume only this
                # PLAN dispatch claim so it cannot bypass the epic guard via
                # the same call's standalone refill pool.
                release_batch_in_flight(
                    self._store,
                    {candidate.id},
                    expected_stage="plan",
                )
                logger.info(
                    "Skipping standalone re-dispatch of epic child #%d "
                    "already handled in this plan cycle",
                    candidate.id,
                )
            return []

        standalone_results = await run_refilling_pool(
            supply_fn=_supply_standalone,
            worker_fn=_plan_worker,
            max_concurrent=self._config.max_planners,
            stop_event=self._stop_event,
            # Opt in to mid-run refill (issue #10296): wake at least every
            # poll_interval to dispatch items enqueued while a long plan holds
            # a slot, instead of only refilling when a plan completes.
            poll_interval=self._config.poll_interval,
        )

        return epic_results + standalone_results

"""Plan phase — run planning agents on issues and post results."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import plan_phase_wiki_ingest
from analysis import PlanAnalyzer
from config import HydraFlowConfig
from convergence_recording import record_stage_verdict, signatures_from_concerns
from events import EventBus
from exception_classify import reraise_on_credit_or_bug
from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from harness_insights import FailureCategory, HarnessInsightStore
from models import (
    ConversationTurn,
    DiscoverResult,
    EpicGapReview,
    IssueOutcomeType,
    PipelineStage,
    PlanFinding,
    PlanResult,
    PlanReview,
    ShapeConversation,
    ShapeTurnResult,
    Task,
)
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    _sentry_transaction,
    release_batch_in_flight,
    run_concurrent_batch,
    run_refilling_pool,
    store_lifecycle,
)
from plan_constants import PlanScale
from plan_phase_wiki_ingest import PlanWikiIngestMixin
from planner import PlannerRunner
from repo_wiki import RepoWikiStore
from research_runner import ResearchRunner
from src.adversarial_agents import AgentLike
from src.adversarial_retry_loop import AdversarialRetryLoop
from src.assumption_surfacer import AssumptionSurfacer, SurfacerOutput
from src.pending_concerns import (
    AdversarialState,
    Concern,
    StageRun,
    is_design_decision_concern,
)
from src.plan_council import CouncilTally, PlanCouncil
from src.spec_ac_generator import SpecACGenerator
from src.spec_judge import JudgeResult, SpecJudge
from state import StateTracker
from task_source import TaskTransitioner
from traceability import extract_req_id, missing_required_req_id
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

# Verdict map for ConvergenceLedger boundary recording (ADR-0096 / convergence gate).
# "ADVANCE" = issue moves forward in the pipeline.
# "LOOP_BACK" = issue failed planning and must re-enter the plan stage.
# "ESCALATE" = issue is handed off to HITL.
_PLAN_VERDICT_MAP: dict[str, str] = {
    "success": "ADVANCE",
    "failed": "LOOP_BACK",
    "escalated": "ESCALATE",
}

# Minimum body length for auto-filed sub-issues discovered during planning.
_MIN_ISSUE_BODY_CHARS: int = 50

# Priority labels IssueRefinementLoop manages (#9957). Mirrors
# ``issue_refinement_loop._PRIORITY_LABELS`` — an unprioritized shape fork is
# deferred, not HITL-escalated (#10311).
_PRIORITY_LABELS: tuple[str, ...] = ("P0", "P1", "P2")

# Re-export (god-file decomposition, #10840): the wiki-ingest cluster moved
# verbatim to ``plan_phase_wiki_ingest`` — this keeps the historical
# ``from plan_phase import _run_fallback_ingest_plan`` seam working.
_run_fallback_ingest_plan = plan_phase_wiki_ingest._run_fallback_ingest_plan


# ---------------------------------------------------------------------------
# Plan flow (P3a of #10682, ADR-0111) — edge guards
# ---------------------------------------------------------------------------
#
# The per-issue plan pipeline runs as an explicit ``src.flows.Flow``:
#
#     prepass -> surface -> draft -> council -> route
#         route         --(close / escalate / plain-failure)--> done
#         route         --> write-records -> gate
#         gate          --(design-decision concerns >= K)-----> done  (human-required)
#         gate          --> ready -> done
#
# Node roles map 1:1 to the pre-refactor straight-line ``_plan_one`` body:
#
# * ``prepass``       — research / discover / shape gates (ADR-0107). A shape
#   fork (non-final directions) sets ``result`` + ``_stop`` + ``_skip_tail`` and
#   routes straight to ``done`` (mirrors the old early ``return``s).
# * ``surface``       — AssumptionSurfacer (adversarial stage 1); fetches the
#   ``AdversarialState`` the whole pipeline threads.
# * ``draft``         — the sole LLM actuator: ``PlannerRunner.plan``.
# * ``council``       — PlanCouncil tight-loop (the shared adversarial-review
#   node, ``AdversarialRetryLoop``-wrapped).
# * ``route``         — already-satisfied handling + success/failure disposition;
#   sets ``ts_status`` and either stops (close/escalate/failure) or continues.
# * ``write-records`` — post the plan, analyse, wiki-ingest, ``_write_plan_records``
#   (which folds the touchpoint-expander re-review, ADR-0063 W3b), then the
#   SpecAC+SpecJudge adversarial stages.
# * ``gate``          — the #10659 design-decision gate: >= K design-decision
#   CRITICAL concerns route to ``human-required`` (stops before ``ready``).
# * ``ready``         — the ready swap + discovered-sub-issue filing.
# * ``done``          — terminal sink: post transcript + record the convergence
#   verdict, unless a path opted out via ``_skip_tail``.
#
# Every fail-closed early exit sets ``state['_stop']`` (routed to ``done`` by the
# ``_flow_stopped`` guard). The LLM call lives inside ``draft`` alone; routing
# between nodes is deterministic. The public seam ``_plan_one`` keeps its
# signature and ``PlanResult`` return type — it now builds and runs the flow.


def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to ``done``."""
    return bool(state.get("_stop"))


class PlanPhase(PlanWikiIngestMixin):
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
    # Earlier-adversarial pipeline wiring (ADR-pending)
    # ------------------------------------------------------------------

    def attach_adversarial_agents(
        self,
        *,
        surfacer_agent: AgentLike | None = None,
        council_agents: dict[str, AgentLike] | None = None,
        spec_ac_agent: AgentLike | None = None,
        spec_judge_agent: AgentLike | None = None,
        budget: int = 3,
    ) -> None:
        """Wire the four adversarial-stage agents onto this phase.

        Called by the factory once on construction (or by tests).
        Each agent is independently optional — when ``None``, that
        stage is skipped, the rest of the pipeline runs unchanged.
        All four together enable the full Surfacer → Council → AC →
        Judge sequence around the existing planner + plan_reviewer.

        ``council_agents`` must contain keys ``builder``, ``tester``,
        ``risk_skeptic`` (per ``PlanCouncil``'s contract).
        """
        self._surfacer_agent = surfacer_agent
        self._council_agents = council_agents
        self._spec_ac_agent = spec_ac_agent
        self._spec_judge_agent = spec_judge_agent
        self._adversarial_budget = budget

    def _has_any_adversarial_agent(self) -> bool:
        return (
            self._surfacer_agent is not None
            or self._council_agents is not None
            or self._spec_ac_agent is not None
            or self._spec_judge_agent is not None
        )

    def _persist_adversarial_state(self, issue: Task, adv: AdversarialState) -> None:
        """Persist *adv* into state.json under the issue's key.

        Per contract: every adversarial stage persists before
        returning so the next stage (and implement_phase) can read the
        accumulated pending concerns.
        """
        self._state.set_adversarial_state(issue.id, adv)

    async def _run_assumption_surfacer(
        self, issue: Task, adv: AdversarialState, research_context: str
    ) -> None:
        """Stage 1: surface assumptions + uncertainty concerns.

        One-shot — the surfacer is a read-only critic; there is no
        planner to retry. Concerns are appended to ``adv.pending_concerns``
        and the state is persisted before returning.
        """
        if self._surfacer_agent is None:
            return
        surfacer = AssumptionSurfacer(agent=self._surfacer_agent, phase="plan")
        out: SurfacerOutput = await surfacer.run(
            issue_body=issue.body or "",
            research_context=research_context,
            carryover_concerns=list(adv.pending_concerns),
        )
        adv.pending_concerns.extend(out.concerns)
        adv.current_stage = "assumption_surfacer"
        adv.stage_history.append(
            StageRun(
                stage="assumption_surfacer",
                phase="plan",
                retries=0,
                converged=True,
                concerns_raised=len(out.concerns),
                concerns_forwarded=len(out.concerns),
                oscillation_detected=False,
                duration_ms=0,
            )
        )
        self._persist_adversarial_state(issue, adv)

    async def _run_plan_council(
        self,
        issue: Task,
        adv: AdversarialState,
        plan_text: str,
    ) -> None:
        """Stage 3: PlanCouncil tight-loop around the (already-run) plan.

        Wired via AdversarialRetryLoop with the configured budget.
        Because the planner has already produced its plan and we don't
        currently re-invoke it on Council retry, the loop runs the
        Council with a no-op ``retry`` step so unresolved concerns
        forward forward rather than block. This honors the dark-factory
        contract: never deadlock; surface, persist, forward.
        """
        if self._council_agents is None:
            return
        council = PlanCouncil(agents=self._council_agents)

        async def _critic(_ctx: str) -> CouncilTally:
            return await council.deliberate(
                plan_text=_ctx, pending_concerns=list(adv.pending_concerns)
            )

        async def _retry(_findings: CouncilTally, ctx: str) -> str:
            # The plan text is unchanged on retry — we do not currently
            # re-invoke the planner from inside the council loop. The
            # Council's ``should_retry`` instead drives whether the
            # AdversarialRetryLoop returns convergence on the next pass.
            # In a future pass we may thread a planner-retry callback
            # in here. For now: forward findings (dark-factory
            # contract) once budget is exhausted.
            return ctx

        def _converged(t: CouncilTally) -> bool:
            return not t.should_retry

        loop: AdversarialRetryLoop[str, CouncilTally] = AdversarialRetryLoop(
            budget=self._adversarial_budget,
            event_bus=self._bus,
            issue_id=issue.id,
            phase="plan",
            stage="plan_council",
        )
        # AdversarialRetryLoop.run expects findings to expose a
        # `.findings: list[Concern]` attribute — CouncilTally satisfies
        # that (its dataclass field is named ``findings``).
        _ctx_out, unresolved, metrics = await loop.run_with_metrics(
            plan_text, _critic, _retry, _converged
        )
        adv.pending_concerns.extend(unresolved)
        adv.current_stage = "plan_council"
        adv.stage_history.append(
            StageRun(
                stage="plan_council",
                phase="plan",
                retries=metrics.retries,
                converged=not bool(unresolved),
                concerns_raised=metrics.total_concerns_raised,
                concerns_forwarded=len(unresolved),
                oscillation_detected=metrics.oscillation_detected,
                duration_ms=0,
            )
        )
        self._persist_adversarial_state(issue, adv)

    async def _run_spec_ac_and_judge(
        self,
        issue: Task,
        adv: AdversarialState,
        plan_text: str,
    ) -> None:
        """Stages 5 + 6: draft AC, then judge plan+AC.

        AC generation is one-shot (no retry). The judge runs through
        AdversarialRetryLoop so a FAIL verdict drives the configured
        budget of retries. As with the Council, retry currently does
        not re-invoke the planner — concerns forward on exhaustion per
        the dark-factory contract.
        """
        if self._spec_ac_agent is None or self._spec_judge_agent is None:
            return
        ac_gen = SpecACGenerator(agent=self._spec_ac_agent)
        acceptance_criteria = await ac_gen.draft(plan_text)

        judge = SpecJudge(agent=self._spec_judge_agent)

        async def _critic(_ctx: str) -> JudgeResult:
            return await judge.evaluate(
                plan_text=_ctx,
                acceptance_criteria=acceptance_criteria,
                pending_concerns=list(adv.pending_concerns),
            )

        async def _retry(_result: JudgeResult, ctx: str) -> str:
            return ctx  # see Council retry note above

        def _converged(r: JudgeResult) -> bool:
            return r.verdict == "PASS"

        loop: AdversarialRetryLoop[str, JudgeResult] = AdversarialRetryLoop(
            budget=self._adversarial_budget,
            event_bus=self._bus,
            issue_id=issue.id,
            phase="plan",
            stage="spec_judge",
        )
        _ctx_out, unresolved, metrics = await loop.run_with_metrics(
            plan_text, _critic, _retry, _converged
        )
        adv.pending_concerns.extend(unresolved)
        adv.current_stage = "spec_judge"
        adv.stage_history.append(
            StageRun(
                stage="spec_ac_generator",
                phase="plan",
                retries=0,
                converged=True,
                concerns_raised=0,
                concerns_forwarded=0,
                oscillation_detected=False,
                duration_ms=0,
            )
        )
        adv.stage_history.append(
            StageRun(
                stage="spec_judge",
                phase="plan",
                retries=metrics.retries,
                converged=not bool(unresolved),
                concerns_raised=metrics.total_concerns_raised,
                concerns_forwarded=len(unresolved),
                oscillation_detected=metrics.oscillation_detected,
                duration_ms=0,
            )
        )
        self._persist_adversarial_state(issue, adv)

    def _has_escalation_label(self, issue: Task) -> bool:
        """True if *issue* carries one of ``config.research_escalation_labels``.

        Shared by :meth:`_should_research` and the ADR-0107 discover-helper
        gate (:meth:`_should_discover_helper`) — both treat an
        operator/loop-applied escalation label as a signal that the issue
        warrants deeper pre-planning work.
        """
        escalation_labels = {
            lbl.lower() for lbl in self._config.research_escalation_labels
        }
        return any(tag.lower() in escalation_labels for tag in issue.tags)

    def _is_memory_backlog_issue(self, issue: Task) -> bool:
        """True if *issue* carries a ``config.memory_backlog_label`` tag.

        Memory-backlog issues (ADR-0089) promote a captured *behavioral* memory
        to the find queue. When the shape gate can't pick one enforcement
        direction for one, it resolves as captured (closed) rather than a HITL
        escalation — the memory is already the rule (#10292).
        """
        backlog_labels = {lbl.lower() for lbl in self._config.memory_backlog_label}
        return any(tag.lower() in backlog_labels for tag in issue.tags)

    def _has_priority_label(self, issue: Task) -> bool:
        """True if *issue* carries a P0/P1/P2 priority label (#10311).

        Mirrors ``issue_refinement_loop._PRIORITY_LABELS`` (the labels
        ``IssueRefinementLoop`` manages). A shape fork on an issue WITHOUT one is
        deferred rather than HITL-escalated: HITL is for prioritized human
        direction choices, not unrefined/low-value forks.
        """
        priority = {lbl.lower() for lbl in _PRIORITY_LABELS}
        return any(tag.lower() in priority for tag in issue.tags)

    def _should_research(self, issue: Task) -> bool:
        """Return True if the research pre-pass should run before planning *issue*.

        Research spawns a full extra codebase-exploration subprocess on top of
        the planner's own exploration, so it is gated rather than run for every
        issue. With ``research_enabled`` on and a runner wired, research runs
        only for issues that need the depth:

        - **Escalated** — the issue carries one of
          ``config.research_escalation_labels``.
        - **Cycled / failing to land** — the issue has been routed back to
          planning at least once (route-back count > 0).

        The common first-pass issue skips research and lets the planner explore
        once.
        """
        if not getattr(self._config, "research_enabled", True):
            return False
        if self._research_runner is None:
            return False
        # Cycled / failing to land: routed back from a later stage at least once.
        if self._state.get_route_back_count(issue.id) > 0:
            return True
        # Escalated: operator/loop flagged the issue for deeper handling.
        return self._has_escalation_label(issue)

    def _triage_hints(self, issue: Task) -> tuple[int, bool]:
        """Return ``(clarity_score, needs_discovery)`` triage HINTS for *issue*.

        ADR-0107: Triage no longer treats these as a routing verdict — it
        records them on the issue's ``IssueCache`` classification record and
        the planner's decision gate reads them back here. Missing cache / no
        classification record yet
        (e.g. ``issue_cache`` disabled, or the issue predates classification)
        reads as the well-specified default ``(10, False)`` — the gate's
        conservative "no helper needed" reading.
        """
        if self._issue_cache is None:
            return 10, False
        record = self._issue_cache.latest_classification(issue.id)
        if record is None:
            return 10, False
        return (
            int(record.payload.get("clarity_score", 10)),
            bool(record.payload.get("needs_discovery", False)),
        )

    def _issue_complexity(self, issue: Task) -> int | None:
        """Triage's complexity_score for *issue*; ``None`` when unknown.

        ``None`` (not a sentinel int) marks an unclassified/unreadable
        score so the tier guard can refuse eligibility at EVERY threshold.
        The prior sentinel-10 collapsed 'unknown' into 'confirmed maximal'
        at ``threshold=10`` (a valid config value), silently skipping the
        review for never-classified issues — found by the sampled re-audit
        on #11304 (#11314, audit-upheld).
        """
        if self._issue_cache is None:
            return None
        try:
            record = self._issue_cache.latest_classification(issue.id)
        except (AttributeError, TypeError, ValueError):
            return None
        payload = getattr(record, "payload", None)
        if not isinstance(payload, dict):
            return None
        try:
            return int(payload["complexity_score"])
        except (KeyError, TypeError, ValueError):
            return None

    def _skip_plan_review(self, issue: Task) -> tuple[bool, int]:
        """#11298 size tiering: does this issue skip the adversarial review?

        Returns ``(skip, complexity)``. Skip only when ALL hold: tiering is
        enabled (threshold > 0), triage scored the issue at or below the
        threshold, the issue has never been routed back (a cycled plan is
        evidence the cheap path failed), and it carries no escalation label.
        The implement-side skill gauntlet still reviews the CODE either way —
        this trades plan-stage ceremony, not merge safety.
        """
        threshold = int(getattr(self._config, "plan_review_min_complexity", 0))
        return self._tier_eligible(issue, threshold)

    def _tier_eligible(self, issue: Task, threshold: int) -> tuple[bool, int]:
        """Shared #11298 tier guard: is *issue* simple enough for a light path?

        Returns ``(eligible, complexity)``. Eligible only when ALL hold:
        the threshold is enabled (> 0), triage actually scored the issue
        (an unknown score is ineligible at EVERY threshold — #11314) at or
        below it, the issue has never been routed back (a cycled plan is
        evidence the cheap path failed), and it carries no escalation
        label. An unknown score reports as 10 for logging.
        """
        complexity = self._issue_complexity(issue)
        if complexity is None:
            return False, 10
        if threshold <= 0:
            return False, complexity
        if complexity > threshold:
            return False, complexity
        if self._state.get_route_back_count(issue.id) > 0:
            return False, complexity
        if self._has_escalation_label(issue):
            return False, complexity
        return True, complexity

    def _forced_plan_scale(self, issue: Task) -> PlanScale | None:
        """#11298 size tiering, planner side: force the lite plan scale?

        Returns ``"lite"`` when the issue passes the shared tier guard
        against ``config.planner_lite_min_complexity``, else ``None`` (the
        planner falls back to its own heuristic scale detection). Rides the
        existing lite-plan prompt/validation machinery — no new prompt
        branch. Self-healing escape valve: a lite plan that fails review
        routes back, and the route-back count then disqualifies the issue
        from tiering, so the next round plans at full scale.
        """
        threshold = int(getattr(self._config, "planner_lite_min_complexity", 0))
        eligible, complexity = self._tier_eligible(issue, threshold)
        if eligible:
            logger.info(
                "Issue #%d complexity %d <= %d — forcing lite plan scale (#11298)",
                issue.id,
                complexity,
                threshold,
            )
            return "lite"
        return None

    def _should_discover_helper(self, issue: Task) -> bool:
        """ADR-0107 planner decision gate: run the discover helper before planning?

        Consulted only when a ``DiscoverRunner`` is wired — with no runner
        (e.g. tests that build PlanPhase directly), this always returns False
        and the planner plans without a discovery pre-pass.

        Conservative default (per ADR-0107): a well-specified issue plans
        directly with no helper. The gate fires when any of —

        - **needs_discovery hint** — Triage's LLM flagged the issue as vague.
        - **clarity_score hint** below ``config.clarity_threshold``.
        - **Cycled / failing to land** — routed back to plan at least once
          (``StateTracker.get_route_back_count``).
        - **Escalated** — issue carries a ``research_escalation_labels`` tag.

        Epic children are excluded outright: they are already-scoped
        decomposition output from a parent epic's planning pass, so
        re-running product discovery on them would be redundant.
        """
        if self._discover_runner is None:
            return False
        if self._is_epic_child(issue):
            return False
        clarity_score, needs_discovery = self._triage_hints(issue)
        return (
            needs_discovery
            or clarity_score < self._config.clarity_threshold
            or self._state.get_route_back_count(issue.id) > 0
            or self._has_escalation_label(issue)
        )

    async def _run_discover_helper(
        self, issue: Task, *, guidance: str
    ) -> DiscoverResult | None:
        """Invoke ``DiscoverRunner`` as an on-demand research pre-pass (ADR-0107).

        This is a synchronous in-process helper call, not a stage transition —
        the engine is reused unmodified; only the caller changes. Bounded
        internally by ``config.max_discover_attempts`` /
        ``max_discover_expansions`` (read by ``DiscoverRunner.discover``
        itself), the same knobs that bounded the standalone Discover phase —
        they now bound this planner-invoked sub-step instead. Returns
        ``None`` (never raises) on failure so planning proceeds without a
        research brief rather than being blocked by it.
        """
        assert self._discover_runner is not None  # guarded by caller
        try:
            result = await self._discover_runner.discover(issue, guidance=guidance)
        except Exception as exc:
            # Dark-factory contract: credit/auth/likely-bug exceptions must
            # propagate so the loop pauses on the billing signal instead of
            # silently planning without research.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Discover helper failed for issue #%d — planning without a "
                "research brief",
                issue.id,
                exc_info=True,
            )
            return None
        try:
            await self._prs.post_comment(
                issue.id, self._format_discover_brief(issue, result)
            )
        except Exception:
            logger.warning(
                "Failed to post discover-helper brief for issue #%d",
                issue.id,
                exc_info=True,
            )
        return result

    @staticmethod
    def _format_discover_brief(issue: Task, result: DiscoverResult) -> str:
        """Format a ``DiscoverResult`` as a GitHub comment for the audit trail."""
        lines = [
            "## Discovery Research (planner-invoked helper)",
            "",
            f"*ADR-0107 — issue #{issue.id} routed Triage → Plan directly; "
            f"the planner's decision gate determined discovery research was "
            f"warranted before planning.*",
            "",
            result.research_brief,
        ]
        if result.opportunities:
            lines.extend(["", "### Opportunities", ""])
            lines.extend(f"- {o}" for o in result.opportunities)
        return "\n".join(lines)

    def _should_shape_helper(
        self, issue: Task, discover_result: DiscoverResult | None
    ) -> bool:
        """ADR-0107 planner decision gate: does discovery warrant a shaping turn?

        Only consulted after the discover helper has already run — shaping
        without a discovery brief has nothing to shape. Fires when the brief
        surfaced genuinely divergent opportunities (2+) that need a human
        choice, per ADR-0107's framing of shaping as direction-selection
        rather than open-ended exploration. Requires a ``ShapeRunner`` to be
        wired; with no runner this always returns False.
        """
        if self._shape_runner is None or discover_result is None:
            return False
        return len(discover_result.opportunities) >= 2

    async def _run_shape_helper(
        self, issue: Task, discover_result: DiscoverResult, *, guidance: str
    ) -> ShapeTurnResult | None:
        """Invoke ``ShapeRunner`` for one bounded conversation turn (ADR-0107).

        Reuses the same ``ShapeConversation`` state slot the standalone Shape
        phase used (``StateTracker.get/set_shape_conversation``) so this
        helper composes with that machinery rather than reimplementing it.
        Bounded by ``config.max_shape_turns`` (conversation-length ceiling —
        returns ``None`` once hit, same as the standalone phase forcing
        finalization) and ``config.max_shape_attempts`` (retried internally
        by ``ShapeRunner.run_turn`` against the shape-coherence evaluator).

        Because shaping is human-interactive, a non-final result is NOT
        waited on synchronously — the caller (``_plan_one``) escalates to
        HITL per ADR-0107's "yield to the existing human-steering channel"
        design rather than blocking the plan tick.
        """
        assert self._shape_runner is not None  # guarded by caller
        conv = self._state.get_shape_conversation(issue.id) or ShapeConversation(
            issue_number=issue.id,
            started_at=datetime.now(UTC).isoformat(),
        )
        if len(conv.turns) >= self._config.max_shape_turns:
            logger.warning(
                "Shape helper hit max_shape_turns (%d) for issue #%d without "
                "finalizing",
                self._config.max_shape_turns,
                issue.id,
            )
            return None
        try:
            result = await self._shape_runner.run_turn(
                issue,
                conv,
                research_brief=discover_result.research_brief,
                guidance=guidance,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Shape helper failed for issue #%d", issue.id, exc_info=True)
            return None
        conv.turns.append(
            ConversationTurn(
                role="agent",
                content=result.content,
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        conv.last_activity_at = datetime.now(UTC).isoformat()
        self._state.set_shape_conversation(issue.id, conv)
        return result

    async def _handle_already_satisfied(self, issue: Task, result: PlanResult) -> bool:
        """Validate evidence and close issue as already-satisfied.

        Returns ``True`` if the issue was closed, ``False`` if evidence validation
        failed (caller should fall through to plan failure handling).
        """
        validation_errors = PlannerRunner.validate_already_satisfied_evidence(
            result.summary,
            issue_body=issue.body,
            repo_root=self._config.repo_root,
        )
        if validation_errors:
            error_list = "\n".join(f"- {e}" for e in validation_errors)
            await self._transitioner.post_comment(
                issue.id,
                f"## Already-Satisfied Evidence Rejected\n\n"
                f"The planner claimed this issue is already satisfied, but the "
                f"evidence failed validation:\n\n{error_list}\n\n"
                f"The issue will be escalated for review.\n\n"
                f"---\n"
                f"*Generated by HydraFlow Planner*",
            )
            result.already_satisfied = False
            result.success = False
            result.retry_attempted = True
            result.validation_errors = validation_errors
            result.error = "Already-satisfied evidence rejected: " + "; ".join(
                validation_errors
            )
            logger.warning(
                "Issue #%d already-satisfied evidence rejected: %s",
                issue.id,
                "; ".join(validation_errors),
            )
            return False

        await self._prs.swap_pipeline_labels(issue.id, self._config.dup_label[0])
        await self._transitioner.post_comment(
            issue.id,
            f"## Already Satisfied\n\n"
            f"The planner determined that this issue's requirements "
            f"are already met by the existing codebase.\n\n"
            f"{result.summary}\n\n"
            f"---\n"
            f"*Generated by HydraFlow Planner*",
        )
        await self._transitioner.close_task(issue.id)
        self._state.record_outcome(
            issue.id,
            IssueOutcomeType.ALREADY_SATISFIED,
            reason=result.summary,
            phase="plan",
        )
        self._state.increment_session_counter("planned")
        logger.info("Issue #%d closed as already satisfied", issue.id)
        if self._summarizer and result.transcript:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=issue.id,
                    phase="plan",
                    status="success",
                    issue_title=issue.title,
                    duration_seconds=result.duration_seconds,
                    log_file=self._plan_log_reference(issue.id),
                    issue_labels=issue.tags,
                )
            except (RuntimeError, OSError):
                logger.exception(
                    "Failed to post transcript summary for issue #%d", issue.id
                )
        return True

    async def _is_product_track_issue(self, issue: Task) -> bool:
        """Detect if an issue came through the product discovery/shape track."""
        enriched = await self._store.enrich_with_comments(issue)
        for comment in enriched.comments or []:
            if "DECOMPOSITION REQUIRED" in comment:
                return True
        return False

    async def _run_plan_finalization(
        self, issue: Task, result: PlanResult
    ) -> PlanResult:
        """Post the plan, write records (+ touchpoint re-review), run SpecAC/Judge.

        The pre-gate half of the former ``_handle_plan_success`` (P3a of #10682):
        everything up to — but not including — the #10659 design-decision gate,
        which is now the explicit ``gate`` flow node. Returns the (possibly
        product-track decompose-retried) ``PlanResult`` the ready swap files
        sub-issues from; the caller threads it to :meth:`_swap_plan_to_ready`.
        The original ``PlanResult`` the plan flow transcribes/returns is
        unaffected — the retry rebind was, and stays, local here.
        """
        # Product-track decomposition check: if issue came from Shape and
        # the planner didn't produce enough sub-issues, retry with feedback
        if (
            await self._is_product_track_issue(issue)
            and len(result.new_issues) < 3
            and not getattr(result, "_decompose_retried", False)
        ):
            logger.info(
                "Issue #%d is product-track but planner only produced %d sub-issues "
                "(need ≥3) — retrying with decomposition feedback",
                issue.id,
                len(result.new_issues),
            )
            retry_result = await self._planners.plan(
                issue,
                research_context=(
                    f"IMPORTANT: This issue came through the product track and "
                    f"MUST be decomposed into 3-8 concrete sub-issues using "
                    f"NEW_ISSUES_START/NEW_ISSUES_END markers. Your previous "
                    f"plan only produced {len(result.new_issues)} sub-issues. "
                    f"Break the work into independently implementable pieces."
                ),
            )
            if retry_result.success and len(retry_result.new_issues) >= 3:
                result = retry_result
            else:
                logger.warning(
                    "Decomposition retry for #%d still insufficient (%d issues)",
                    issue.id,
                    len(retry_result.new_issues) if retry_result.success else 0,
                )
                # Proceed with whatever we have

        branch = self._config.branch_for_issue(issue.id)
        score_line = ""
        if result.actionability_rank != "unknown":
            score_line = (
                f"**Actionability score:** {result.actionability_score}/100 "
                f"({result.actionability_rank})\n"
            )
        # Collect any architecture diagrams the planner wrote to /tmp
        diagram_attachments = PlannerRunner.collect_diagram_attachments(issue.id)
        diagram_section = ""
        if diagram_attachments:
            diagram_section = f"\n\n## Architecture Diagrams\n\n{diagram_attachments}\n"

        # CH-5 traceability: carry the requirement ID (req:<id> label or
        # Req-ID: body line) into the plan comment immediately AFTER the
        # "## Implementation Plan" heading, ABOVE the plan body. The
        # implementer prompt extracts the plan from the heading up to the
        # FIRST ^---$ line (AgentRunner._strip_plan_noise, agent.py) — a
        # bare horizontal rule inside the plan body would sever anything
        # placed below it, so the Req-ID must lead.
        req_id = extract_req_id(labels=issue.tags, body=issue.body)
        req_line = f"**Req-ID:** `{req_id}`\n\n" if req_id else ""
        req_warning = ""
        if missing_required_req_id(
            labels=issue.tags,
            body=issue.body,
            regulated_labels=self._config.regulated_label_set(),
        ):
            req_warning = (
                "> ⚠️ **Req-ID required:** this issue is in the regulated "
                "change class but declares no requirement ID. Add a "
                "`req:<id>` label or a `Req-ID:` line to the issue body so "
                "the change is traceable in the requirements matrix.\n\n"
            )

        comment_body = (
            f"## Implementation Plan\n\n"
            f"{req_line}"
            f"{req_warning}"
            f"{result.plan}\n\n"
            f"{diagram_section}"
            f"**Branch:** `{branch}`\n\n"
            f"---\n"
            f"{score_line}"
            f"*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(issue.id, comment_body)

        analyzer = PlanAnalyzer(repo_root=self._config.repo_root)
        analysis = analyzer.analyze(result.plan, issue.id)
        await self._transitioner.post_comment(issue.id, analysis.format_comment())

        # Ingest plan knowledge into the per-repo wiki
        await self._wiki_ingest_plan(issue.id, result.plan)

        # IMPORTANT: cache writes (plan_stored + review_stored) and the
        # adversarial reviewer MUST run BEFORE the label swap to ready.
        # If the swap happened first, the implement loop could pick up
        # the issue and the READY-stage precondition gate would find
        # no records and route the issue back to plan — causing an
        # infinite ping-pong loop. The eager-transition guard at
        # `enqueue_transition` is in-memory only and does not protect
        # against the GitHub label being visible to other pollers.
        await self._write_plan_records(issue, result)

        # Earlier-adversarial pipeline stages 5+6: SpecACGenerator + SpecJudge.
        # Run AFTER PlanReviewer (which is invoked from inside
        # ``_write_plan_records``). No-op when SpecAC/Judge agents are
        # not configured.
        if (
            self._spec_ac_agent is not None
            and self._spec_judge_agent is not None
            and result.plan
        ):
            adv = self._state.get_adversarial_state(issue.id) or AdversarialState(
                phase="plan"
            )
            try:
                await self._run_spec_ac_and_judge(issue, adv, result.plan)
            except Exception as exc:  # noqa: BLE001
                # Dark-factory contract: credit-exhaustion / auth / likely-bug
                # exceptions MUST propagate so the outer loop pauses on the
                # billing signal instead of swallowing it and marching the
                # issue toward 'ready'. Everything else soft-fails (concerns
                # forward unchanged).
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "SpecAC/Judge stage failed for issue #%d — forwarding "
                    "concerns unchanged",
                    issue.id,
                    exc_info=True,
                )
        return result

    async def _swap_plan_to_ready(self, issue: Task, result: PlanResult) -> None:
        """Swap the issue to ``hydraflow-ready`` and file discovered sub-issues.

        The post-gate half of the former ``_handle_plan_success`` (P3a of
        #10682). Reached from the ``ready`` flow node only when the #10659
        design-decision ``gate`` did NOT route the issue to ``human-required``.
        """
        # Activate eager-transition protection BEFORE the GitHub label swap
        # so that concurrent polling cannot re-queue the issue during the
        # non-atomic label add/remove window.
        self._store.enqueue_transition(issue, "ready")
        await self._transitioner.transition(issue.id, "ready")

        for new_issue in result.new_issues:
            if len(new_issue.body) < _MIN_ISSUE_BODY_CHARS:
                logger.warning(
                    "Skipping discovered issue %r — body too short "
                    "(%d chars, need ≥%d)",
                    new_issue.title,
                    len(new_issue.body),
                    _MIN_ISSUE_BODY_CHARS,
                )
                continue
            labels = new_issue.labels or [self._config.planner_label[0]]
            await self._transitioner.create_task(
                new_issue.title, new_issue.body, labels
            )
            self._state.record_issue_created()

        if result.duration_seconds > 0:
            self._state.record_plan_duration(result.duration_seconds)
        self._state.increment_session_counter("planned")
        logger.info("Plan posted and labels swapped for issue #%d", issue.id)

    async def _route_to_hitl_if_design_decision(self, issue: Task) -> bool:
        """Route to ``human-required`` when plan review needs a human decision.

        Issue #10659: when the accumulated ``AdversarialState`` for *issue*
        holds at least ``plan_design_decision_hitl_threshold`` design-decision-
        class CRITICAL concerns (unresolved design decision / unvalidated core
        mechanism — see ``is_design_decision_concern``), the issue is NOT ready
        to implement. Swap it to ``human-required`` (which is orthogonal to the
        stage machine and skipped by every pipeline queue) instead of
        ``hydraflow-ready``, post an explanatory comment listing the concerns,
        and clear the adversarial state so a post-design re-queue starts fresh.

        Returns ``True`` when the issue was routed to HITL (caller must NOT
        proceed to the ready swap), ``False`` otherwise (normal flow to ready).
        """
        adv = self._state.get_adversarial_state(issue.id)
        if adv is None:
            return False
        design_concerns: list[Concern] = [
            c for c in adv.pending_concerns if is_design_decision_concern(c)
        ]
        threshold = self._config.plan_design_decision_hitl_threshold
        if len(design_concerns) < threshold:
            return False

        concern_lines = "\n".join(
            f"- **[{c.severity}|{c.raised_in_stage}]** {c.concern}"
            for c in design_concerns
        )
        comment = (
            "## Design decision required — routed to `human-required`\n\n"
            f"Plan review surfaced **{len(design_concerns)}** unresolved "
            "design-decision / unvalidated-core-mechanism concern(s) "
            f"(threshold: {threshold}). These need a human decision "
            "(brainstorm → spec) before implementation — forwarding them to the "
            "implementer causes the build agent to hang to the timeout and "
            "retry-thrash on an underspecified feature (#10659).\n\n"
            f"{concern_lines}\n\n"
            "Re-apply a pipeline label once the design is decided.\n\n"
            "---\n*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(issue.id, comment)
        # Clear adversarial state before the HITL hand-off so a post-design
        # re-queue starts fresh (mirrors the other HITL escalation paths) —
        # otherwise pending_concerns grows unboundedly across cycles.
        self._state.clear_adversarial_state(issue.id)
        await self._prs.swap_pipeline_labels(issue.id, "human-required")
        logger.warning(
            "Issue #%d routed to human-required — %d design-decision CRITICAL "
            "concern(s) >= threshold %d (not swapping to ready)",
            issue.id,
            len(design_concerns),
            threshold,
        )
        return True

    async def _write_plan_records(self, issue: Task, result: PlanResult) -> int:
        """Write plan_stored + review_stored cache records.

        Called BEFORE the label swap to ready so the records exist
        before the implement loop can observe the new label and run
        the READY-stage precondition gate. Returns the plan version
        assigned by the cache (1 if no cache configured).

        Best-effort across both writes — failures log at warning and
        do not raise into the caller, so the plan still proceeds and
        the gate handles the missing-record case via route-back with
        the cause "no review_stored record" (effectively the same as
        a blocking review, with a clearer human-readable cause).

        Adversarial findings live in the review_stored record, not in
        plan_stored — conflating validation_errors with PlanFinding-
        shaped findings would poison the cache for review-stage
        consumers.
        """
        plan_version = 1
        if self._issue_cache is None:
            return plan_version

        plan_version = self._issue_cache.record_plan_stored(
            issue.id,
            plan_text=result.plan,
            actionability_score=result.actionability_score,
        )

        if self._plan_reviewer is None:
            return plan_version

        # #11298 size tiering: low-complexity, never-cycled, unescalated
        # issues skip the agentic review spawn. A review_stored record is
        # still written (has_blocking=False) so the READY-stage gate's
        # "no review_stored record" route-back never fires for the light
        # tier — the skip is an explicit, audited verdict, not a gap.
        skip, complexity = self._skip_plan_review(issue)
        if skip:
            threshold = self._config.plan_review_min_complexity
            summary = (
                f"light-tier: adversarial plan review skipped "
                f"(complexity {complexity} <= {threshold}; #11298)"
            )
            logger.info("Plan review skipped for issue #%d — %s", issue.id, summary)
            self._issue_cache.record_review_stored(
                issue.id,
                review_text=summary,
                has_blocking=False,
                findings=[],
            )
            return plan_version

        try:
            # #11298 delta re-review: after a route-back this is round >= 2 —
            # feed the prior round's cached findings so the reviewer verifies
            # fixes instead of re-exploring the repo (plan_reviewer measured
            # at 42% of all factory tokens, dominated by re-exploration).
            prior_summary, prior_findings = self._prior_review_context(issue.id)
            review = await self._plan_reviewer.review(
                issue,
                result,
                plan_version=plan_version,
                prior_summary=prior_summary,
                prior_findings=prior_findings,
            )
            # ADR-0063 W3b: on the FIRST blocking review, dispatch the
            # touchpoint-expander (if wired) and re-run the reviewer
            # against an enriched plan. Bounded to one expansion attempt
            # — if the second pass still flags blocking findings, the
            # existing READY-stage gate routes the issue back to plan
            # (or escalates after the per-issue route-back cap).
            review = await self._maybe_expand_touchpoints(
                issue, result, review, plan_version
            )
            if review.success:
                self._issue_cache.record_review_stored(
                    issue.id,
                    review_text=review.summary,
                    has_blocking=review.has_blocking_findings,
                    findings=[f.model_dump() for f in review.findings],
                )
                if review.has_blocking_findings:
                    logger.warning(
                        "Plan review for issue #%d found blocking "
                        "findings — READY-stage gate will route back "
                        "to PLAN: %s",
                        issue.id,
                        review.summary,
                    )
            else:
                logger.warning(
                    "Plan review skipped for issue #%d: %s",
                    issue.id,
                    review.error or "reviewer returned no result",
                )
        except Exception:
            logger.warning(
                "Plan reviewer raised for issue #%d — leaving plan "
                "without a review record",
                issue.id,
                exc_info=True,
            )

        return plan_version

    def _prior_review_context(
        self, issue_id: int
    ) -> tuple[str | None, list[PlanFinding] | None]:
        """Prior round's cached review (summary, findings) for issue_id.

        (None, None) on round 1 (no cached review) or when the cache is
        unavailable/malformed — the reviewer then runs a normal full
        first-round review (#11298 delta re-review is fail-open).
        """
        if self._issue_cache is None:
            return None, None
        try:
            record = self._issue_cache.latest_review(issue_id)
            payload = getattr(record, "payload", None)
            if not isinstance(payload, dict):
                return None, None
            summary = payload.get("review_text") or None
            findings: list[PlanFinding] = []
            for raw in payload.get("findings") or []:
                try:
                    findings.append(PlanFinding.model_validate(raw))
                except (ValueError, TypeError):
                    continue  # one bad row never blocks review
            if not isinstance(summary, str):
                summary = None
            return summary, (findings or None)
        except (AttributeError, TypeError, ValueError):
            # Malformed cache (or a test double with a different shape) —
            # degrade to a normal full first-round review.
            return None, None

    async def _maybe_expand_touchpoints(
        self,
        issue: Task,
        result: PlanResult,
        first_review: PlanReview,
        plan_version: int,
    ) -> PlanReview:
        """Run the touchpoint-expander + re-review on FIRST blocking failure.

        Returns the review that should be cached. When no expander is
        wired, the first review has no blocking findings, the expander
        surfaces no touchpoints, or the reviewer is missing, returns
        ``first_review`` unchanged so the existing route-back path runs.

        Bounded to one expansion attempt per ADR-0063 W3b — the second
        review's verdict (clean or still-blocking) is what the cache
        records. A still-blocking second review routes back via the
        existing READY-stage gate.
        """
        if (
            self._touchpoint_expander is None
            or self._plan_reviewer is None
            or not first_review.success
            or not first_review.has_blocking_findings
        ):
            return first_review

        try:
            expansion = await self._touchpoint_expander.expand_touchpoints(
                original_plan=result.plan,
                reviewer_failure=first_review,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Touchpoint expander raised for issue #%d — falling back "
                "to existing route-back path",
                issue.id,
                exc_info=True,
            )
            return first_review

        context_block = expansion.render_context_block()
        if not context_block:
            logger.info(
                "Touchpoint expander surfaced no touchpoints for issue #%d "
                "— skipping re-review",
                issue.id,
            )
            return first_review

        # Build an enriched plan_result for the second review pass. We
        # do NOT mutate the original result — the cached plan_stored
        # record (already written above) reflects the planner's output,
        # not the enrichment. The expansion is a reviewer-side aid.
        enriched_plan = f"{result.plan}\n\n{context_block}"
        enriched_result = result.model_copy(update={"plan": enriched_plan})

        try:
            second_review = await self._plan_reviewer.review(
                issue,
                enriched_result,
                plan_version=plan_version,
                prior_summary=first_review.summary,
                prior_findings=list(first_review.findings),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Re-review with expanded touchpoints raised for issue #%d "
                "— falling back to original review",
                issue.id,
                exc_info=True,
            )
            return first_review

        logger.info(
            "Touchpoint-expander re-review for issue #%d: %d touchpoints "
            "surfaced, blocking=%s → %s",
            issue.id,
            len(expansion.touchpoints),
            first_review.has_blocking_findings,
            second_review.has_blocking_findings,
        )
        return second_review

    # _wiki_ingest_plan / _wiki_tracked_store / _precompute_corroboration /
    # _wiki_commit_compiler_entries are provided by PlanWikiIngestMixin
    # (plan_phase_wiki_ingest.py) — extracted verbatim, #10840.

    async def _handle_plan_failure(self, issue: Task, result: PlanResult) -> None:
        """Post comment, escalate to HITL, record harness failure."""
        error_list = "\n".join(f"- {e}" for e in result.validation_errors)
        score_line = ""
        if result.actionability_rank != "unknown":
            score_line = (
                f"**Actionability score:** {result.actionability_score}/100 "
                f"({result.actionability_rank})\n\n"
            )
        hitl_comment = (
            f"## Plan Validation Failed\n\n"
            f"The planner was unable to produce a valid plan "
            f"after planning attempts for issue #{issue.id}.\n\n"
            f"{score_line}"
            f"**Validation errors:**\n{error_list}\n\n"
            f"---\n"
            f"*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(issue.id, hitl_comment)
        # Clear any accumulated adversarial state before HITL hand-off. Next
        # retry (after operator re-labels to hydraflow-ready) starts with a
        # fresh AdversarialState — otherwise the surfacer's concerns would
        # be appended on top of the prior attempt's, growing unboundedly
        # across HITL cycles.
        self._state.clear_adversarial_state(issue.id)
        await self._escalator(
            issue,
            cause="Plan validation failed after retry",
            details="; ".join(result.validation_errors),
            category=FailureCategory.PLAN_VALIDATION,
        )
        logger.warning(
            "Planning failed validation for issue #%d after retry — escalated to HITL",
            issue.id,
        )

    async def _post_plan_transcript(
        self, issue: Task, result: PlanResult, *, status: str
    ) -> None:
        """File memory suggestion and post transcript summary."""
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "planner", f"issue #{issue.id}"
            )
        if self._summarizer and result.transcript:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=issue.id,
                    phase="plan",
                    status=status,
                    issue_title=issue.title,
                    duration_seconds=result.duration_seconds,
                    log_file=self._plan_log_reference(issue.id),
                    issue_labels=issue.tags,
                )
            except (RuntimeError, OSError):
                logger.exception(
                    "Failed to post transcript summary for issue #%d", issue.id
                )

    def _plan_log_reference(self, issue_number: int) -> str:
        """Return a display-friendly log path for planner transcripts."""
        log_path = self._config.log_dir / f"plan-issue-{issue_number}.txt"
        return self._config.format_path_for_display(log_path)

    # ------------------------------------------------------------------
    # Epic group planning helpers
    # ------------------------------------------------------------------

    def _is_epic_child(self, issue: Task) -> bool:
        """Return True if *issue* has an epic-child label."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        return bool(epic_child_labels & {t.lower() for t in issue.tags})

    def _resolve_epic_number(self, issue: Task) -> int | None:
        """Extract the parent epic number from metadata or body text."""
        epic_num = issue.metadata.get("epic_number")
        if epic_num:
            return int(epic_num)
        match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", issue.body)
        if match:
            return int(match.group(1))
        return None

    def _group_by_epic(
        self, issues: list[Task]
    ) -> tuple[dict[int, list[Task]], list[Task]]:
        """Partition issues into ``{epic_number: [children]}`` and standalone.

        Issues with an epic-child label whose parent cannot be resolved
        are placed in the standalone list.
        """
        epic_groups: dict[int, list[Task]] = {}
        standalone: list[Task] = []
        for issue in issues:
            if not self._is_epic_child(issue):
                standalone.append(issue)
                continue
            epic_num = self._resolve_epic_number(issue)
            if epic_num is None:
                standalone.append(issue)
                continue
            epic_groups.setdefault(epic_num, []).append(issue)
        return epic_groups, standalone

    @staticmethod
    def _parse_gap_review(transcript: str, epic_number: int) -> EpicGapReview:
        """Parse an ``EpicGapReview`` from a gap-review transcript."""
        review = EpicGapReview(epic_number=epic_number)

        start_marker = "GAP_REVIEW_START"
        end_marker = "GAP_REVIEW_END"
        start_idx = transcript.find(start_marker)
        end_idx = transcript.find(end_marker)
        if start_idx == -1:
            return review
        body = transcript[
            start_idx + len(start_marker) : end_idx if end_idx != -1 else None
        ]

        # Extract findings
        findings_match = re.search(
            r"##\s*Findings\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if findings_match:
            review.findings = findings_match.group(1).strip()

        # Extract re-plan issues
        replan_match = re.search(
            r"##\s*Re-plan Required\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if replan_match:
            replan_text = replan_match.group(1).strip()
            if replan_text.lower() != "none":
                review.replan_issues = list(
                    dict.fromkeys(
                        int(m.group(1)) for m in re.finditer(r"#(\d+)", replan_text)
                    )
                )

        # Extract guidance
        guidance_match = re.search(
            r"##\s*Guidance\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if guidance_match:
            review.guidance = guidance_match.group(1).strip()

        return review

    async def _plan_one(
        self,
        idx: int,
        issue: Task,
        semaphore: asyncio.Semaphore,
    ) -> PlanResult:
        """Plan a single issue (shared by standalone and epic flows).

        Runs the per-issue plan pipeline as an explicit ``src.flows.Flow`` (P3a
        of #10682, ADR-0111): ``prepass -> surface -> draft -> council -> route
        -> (write-records -> gate -> ready) -> done``. Signature and
        ``PlanResult`` return contract are unchanged; the outer scaffolding
        (stop-event checks, planner semaphore, sentry span, store lifecycle)
        stays here and the pipeline body is the flow.
        """
        if self._stop_event.is_set():
            return PlanResult(issue_number=issue.id, error="stopped")

        async with semaphore:
            if self._stop_event.is_set():
                return PlanResult(issue_number=issue.id, error="stopped")

            with _sentry_transaction("pipeline.plan", f"plan:#{issue.id}"):
                async with store_lifecycle(self._store, issue.id, "plan"):
                    return await self._plan_one_inner(idx, issue)

    async def _plan_one_inner(self, idx: int, issue: Task) -> PlanResult:
        """Build and run the per-issue plan flow, returning the ``PlanResult``.

        The straight-line pipeline body of the pre-refactor ``_plan_one`` is now
        the flow (see the module-level diagram). The final ``PlanResult`` is read
        off the terminal state's ``result`` key.
        """
        flow = self._build_plan_flow()
        outcome = await flow.run(self._initial_plan_state(idx, issue))
        return outcome.state["result"]

    @staticmethod
    def _initial_plan_state(idx: int, issue: Task) -> FlowState:
        """Seed the plan flow's shared working state for one issue."""
        return {"idx": idx, "issue": issue}

    def _build_plan_flow(
        self,
        *,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> Flow:
        """Build the per-issue plan DAG (P3a of #10682, ADR-0111).

        See the module-level diagram for node roles. ``checkpoint`` /
        ``kill_switch`` stay injected per ADR-0111 so the primitive's
        persistence + halt seams are wired-through and testable. The production
        entry runs without a checkpoint: a single plan tick needs no resume, and
        writing one would be a new on-disk side effect this parity-gated, no-flag
        refactor must not introduce. Per-node ``on_node`` event wiring is
        deferred to a later phase per ADR-0111.
        """
        return Flow(
            nodes=[
                Node("prepass", self._flow_prepass, kind="gate"),
                Node("surface", self._flow_surface),
                Node("draft", self._flow_draft),
                Node("council", self._flow_council, kind="loop"),
                Node("route", self._flow_route, kind="gate"),
                Node("write-records", self._flow_write_records),
                Node("gate", self._flow_gate, kind="gate"),
                Node("ready", self._flow_ready),
                Node("done", self._flow_done),
            ],
            edges=[
                # First-match-wins: a stopped node skips straight to the sink.
                Edge("prepass", "done", when=_flow_stopped),
                Edge("prepass", "surface"),
                Edge("surface", "draft"),
                Edge("draft", "council"),
                Edge("council", "route"),
                Edge("route", "done", when=_flow_stopped),
                Edge("route", "write-records"),
                Edge("write-records", "gate"),
                Edge("gate", "done", when=_flow_stopped),
                Edge("gate", "ready"),
                Edge("ready", "done"),
            ],
            entry="prepass",
            checkpoint=checkpoint,
            kill_switch=kill_switch,
        )

    # -- flow nodes ---------------------------------------------------------

    async def _route_light_lane(self, issue: Task, state: FlowState) -> bool:
        """#11298 light lane: route a triage-scored simple issue to the
        single-session auto-agent (one spawn: read issue -> implement ->
        test -> PR) instead of the staged plan/review pipeline.

        The claim-label swap removes the issue from every plan-stage
        queue; AutoAgentPreflightLoop polls the claim label for intake and
        crash recovery. Shared _tier_eligible guard: cycled, escalated, or
        unscored issues never route here, and an auto-agent exhaustion
        falls BACK to this pipeline (never to a human). Returns True when
        routed (the flow stops); mutates *state* accordingly.
        """
        if not self._config.auto_agent_light_intake_enabled:
            return False
        if not self._config.auto_agent_preflight_enabled:
            # Stranding guard: routing claims the issue out of every queue,
            # so never route when the consuming loop is config-disabled —
            # the claim label has no TTL redrive of its own.
            return False
        eligible, complexity = self._tier_eligible(
            issue, self._config.auto_agent_light_max_complexity
        )
        if not eligible:
            return False
        logger.info(
            "Issue #%d complexity %d <= %d — routing to the "
            "auto-agent light lane (#11298)",
            issue.id,
            complexity,
            self._config.auto_agent_light_max_complexity,
        )
        await self._prs.swap_pipeline_labels(
            issue.id, self._config.light_autofix_label[0]
        )
        state["result"] = PlanResult(
            issue_number=issue.id,
            success=True,
            summary=(
                f"light-lane: routed to single-session auto-agent "
                f"(complexity {complexity}; #11298)"
            ),
        )
        state["_stop"] = True
        state["_skip_tail"] = True
        return True

    async def _flow_prepass(self, state: FlowState) -> FlowState:
        """Research / discover / shape gates (ADR-0107) before drafting.

        Reproduces the head of the pre-refactor ``_plan_one`` body. A shape fork
        (non-final directions: memory-backlog / unprioritized close, or a
        prioritized HITL escalation) sets ``result`` + ``_stop`` + ``_skip_tail``
        and routes straight to ``done`` — the flow analogue of the old early
        ``return``s (which posted no transcript / verdict).
        """
        issue = state["issue"]

        if await self._route_light_lane(issue, state):
            return state

        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""
        research_context = ""
        if self._should_research(issue):
            research_result = await self._research_runner.research(issue)  # type: ignore[union-attr]
            if research_result.success:
                research_context = research_result.research
                logger.info(
                    "Research completed for issue #%d (%d chars)",
                    issue.id,
                    len(research_context),
                )
                # Post collapsed research as issue comment
                try:
                    await self._prs.post_comment(
                        issue.id,
                        f"<details><summary>🔬 Research Context</summary>\n\n"
                        f"{research_context}\n\n</details>",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to post research comment for #%d",
                        issue.id,
                        exc_info=True,
                    )
            else:
                logger.warning(
                    "Research failed for issue #%d: %s",
                    issue.id,
                    research_result.error,
                )

        # ADR-0107: the planner's on-demand discover/shape
        # decision gate. Both gates return False when no runner is
        # wired (e.g. tests that build PlanPhase directly), so this
        # block is a no-op there; in production the gate decides,
        # per issue, whether a discovery pre-pass / shaping turn is
        # warranted before planning.
        discover_result: DiscoverResult | None = None
        if self._should_discover_helper(issue):
            discover_result = await self._run_discover_helper(
                issue, guidance=human_guidance
            )
            if discover_result is not None:
                research_context = (
                    f"{research_context}\n\n{discover_result.research_brief}"
                ).strip()

            if self._should_shape_helper(issue, discover_result):
                assert discover_result is not None  # gate requires it
                shape_result = await self._run_shape_helper(
                    issue, discover_result, guidance=human_guidance
                )
                if shape_result is None or not shape_result.is_final:
                    # Divergent directions need a human choice.
                    # Shaping is human-interactive (ADR-0107) —
                    # yield to the existing HITL / human-steering
                    # channel instead of blocking this plan tick
                    # on a synchronous wait for a reply.
                    options_text = (
                        shape_result.content
                        if shape_result is not None
                        else "Shaping could not produce directions "
                        "within the configured turn budget."
                    )
                    # A shape fork does NOT escalate to HITL unless
                    # it's a prioritized human-direction choice. A
                    # memory-backlog issue (ADR-0089 behavioral
                    # capture) resolves as CAPTURED — the memory IS
                    # the rule (#10292); any other UNPRIORITIZED issue
                    # is DEFERRED — HITL is for P0-P2 forks (#10311).
                    # Both close with a re-engage path instead of
                    # piling a low-value fork into HITL + the diagnose
                    # loop.
                    is_backlog = self._is_memory_backlog_issue(issue)
                    if is_backlog or not self._has_priority_label(issue):
                        if is_backlog:
                            detail = (
                                "*This is a memory-backlog "
                                "(behavioral) issue (ADR-0089): the "
                                "captured memory stands as the rule "
                                "and no one enforcement direction is "
                                "clearly warranted. Closed as "
                                "captured. Re-file a `hydraflow-find` "
                                "with an EXPLICIT direction to build "
                                "enforcement (#10292).*"
                            )
                            error = "memory_backlog_shape_captured"
                            why = "memory-backlog fork closed as captured"
                        else:
                            detail = (
                                "*This issue has no P0/P1/P2 priority, "
                                "so divergent directions were surfaced "
                                "but NOT escalated to HITL (reserved "
                                "for prioritized choices). Deferred — "
                                "set a P0-P2 priority or re-file with "
                                "an explicit direction to proceed "
                                "(#10311).*"
                            )
                            error = "shape_deferred_unprioritized"
                            why = "unprioritized fork deferred"
                        await self._transitioner.post_comment(
                            issue.id,
                            "## Shaping — no HITL escalation\n\n"
                            f"{options_text}\n\n---\n{detail}",
                        )
                        await self._transitioner.close_task(issue.id)
                        logger.info(
                            "Issue #%d %s, not HITL-escalated",
                            issue.id,
                            why,
                        )
                        state["result"] = PlanResult(issue_number=issue.id, error=error)
                        state["_stop"] = True
                        state["_skip_tail"] = True
                        return state
                    try:
                        await self._prs.post_comment(
                            issue.id,
                            "## Product Directions (planner-invoked "
                            f"shaping helper)\n\n{options_text}\n\n"
                            "---\n*A human choice is needed before "
                            "planning can continue — reply with your "
                            "preferred direction or use human "
                            "steering, then re-queue for planning.*",
                        )
                    except Exception:
                        logger.warning(
                            "Failed to post shape-helper options for issue #%d",
                            issue.id,
                            exc_info=True,
                        )
                    await self._escalator(
                        issue,
                        cause="Shape helper surfaced divergent "
                        "product directions needing a human choice",
                        details=options_text[:500],
                        category=FailureCategory.HITL_ESCALATION,
                    )
                    logger.info(
                        "Issue #%d shape helper escalated to HITL "
                        "for a direction choice",
                        issue.id,
                    )
                    state["result"] = PlanResult(
                        issue_number=issue.id, error="shape_escalated"
                    )
                    state["_stop"] = True
                    state["_skip_tail"] = True
                    return state
                # Finalized on this turn — fold the selected
                # direction into research_context (synchronous,
                # no re-fetch needed) and require the same
                # decomposition the standalone Shape phase asked
                # for, since this is still a broad product
                # direction rather than one implementable task.
                research_context = (
                    f"{research_context}\n\n{shape_result.content}\n\n"
                    "IMPORTANT — DECOMPOSITION REQUIRED: this issue "
                    "came through the ADR-0107 planner-invoked shaping "
                    "helper and MUST be decomposed into 3-8 concrete "
                    "sub-issues using NEW_ISSUES_START/NEW_ISSUES_END "
                    "markers."
                ).strip()
                try:
                    await self._prs.post_comment(
                        issue.id,
                        "## Final Product Direction (planner-invoked "
                        f"shaping helper)\n\n{shape_result.content}\n\n"
                        "\n### Planning Guidance — DECOMPOSITION "
                        "REQUIRED\n\nThis issue was shaped via the "
                        "planner's on-demand helper. It is a BROAD "
                        "product direction, NOT a single "
                        "implementable task. You MUST decompose this "
                        "into 3-8 concrete sub-issues using the "
                        "NEW_ISSUES_START/NEW_ISSUES_END format.",
                    )
                except Exception:
                    logger.warning(
                        "Failed to post finalized shape direction for issue #%d",
                        issue.id,
                        exc_info=True,
                    )
        state["human_guidance"] = human_guidance
        state["research_context"] = research_context
        return state

    async def _flow_surface(self, state: FlowState) -> FlowState:
        """Adversarial stage 1 (AssumptionSurfacer) + fetch the AdversarialState.

        ``adv`` is fetched unconditionally (the whole pipeline threads it, and
        the terminal verdict signs off on its concerns) and stashed in state so
        every downstream node — and the ``done`` tail — reads the same object.
        """
        issue = state["issue"]
        research_context = state["research_context"]
        adv = self._state.get_adversarial_state(issue.id) or AdversarialState(
            phase="plan"
        )
        state["adv"] = adv
        if self._surfacer_agent is not None:
            try:
                await self._run_assumption_surfacer(issue, adv, research_context)
            except Exception as exc:  # noqa: BLE001
                # Dark-factory contract: credit/auth/likely-bug from the surfacer
                # agent must propagate so the loop pauses rather than marching the
                # issue forward.
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "AssumptionSurfacer failed for issue #%d — "
                    "forwarding to planner unchanged",
                    issue.id,
                    exc_info=True,
                )
        return state

    async def _flow_draft(self, state: FlowState) -> FlowState:
        """The sole LLM actuator: run the planner and record its ``PlanResult``.

        Behaviour is unchanged from the pre-refactor ``_plan_one`` body — tracing
        context is set/cleared around the single ``PlannerRunner.plan`` call and
        the phase rollup is written in the ``finally``.
        """
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import (  # noqa: PLC0415
            TracingContext,
            source_to_phase,
        )

        issue = state["issue"]
        idx = state["idx"]
        research_context = state["research_context"]
        human_guidance = state["human_guidance"]

        trace_phase = source_to_phase("planner")
        run_id = self._state.begin_trace_run(issue.id, trace_phase)
        self._planners.set_tracing_context(
            TracingContext(
                issue_number=issue.id,
                phase=trace_phase,
                source="planner",
                run_id=run_id,
            )
        )
        try:
            result = await self._planners.plan(
                issue,
                worker_id=idx,
                research_context=research_context,
                guidance=human_guidance,
                force_scale=self._forced_plan_scale(issue),
            )
        finally:
            self._planners.clear_tracing_context()
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=issue.id,
                    phase=trace_phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for issue #%d",
                    issue.id,
                    exc_info=True,
                )
            self._state.end_trace_run(issue.id, trace_phase)
        state["result"] = result
        return state

    async def _flow_council(self, state: FlowState) -> FlowState:
        """Adversarial stage 3: PlanCouncil tight-loop over the drafted plan.

        The shared adversarial-review node (``AdversarialRetryLoop``-wrapped);
        no-op when council agents are not configured or the draft failed. The
        same delegation seam (``_run_plan_council``) P3b/P3c reuse.
        """
        issue = state["issue"]
        adv = state["adv"]
        result = state["result"]
        skip, complexity = self._skip_plan_review(issue)
        if skip:
            # #11298 light tier skips the council too: the council critiques
            # a deliberately-short LITE plan against full-scale expectations,
            # raising design-decision concerns that no reviewer stage will
            # resolve — observed live 2026-08-16 as a mass HITL cascade
            # (every light-tier issue routed to human-required at the
            # ready-swap design gate). The gate itself stays armed: concerns
            # raised by earlier stages still route genuinely ambiguous
            # issues to HITL, and cycled issues get the full stack again.
            logger.info(
                "PlanCouncil skipped for issue #%d — light-tier "
                "(complexity %d; #11298)",
                issue.id,
                complexity,
            )
            state["result"] = result
            return state
        if self._council_agents is not None and result.success and result.plan:
            try:
                await self._run_plan_council(issue, adv, result.plan)
            except Exception as exc:  # noqa: BLE001
                # Dark-factory contract: a voter that exhausted credit MUST
                # surface so the loop pauses on the billing signal instead of
                # forwarding a half-empty tally toward 'ready'.
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "PlanCouncil failed for issue #%d — forwarding concerns unchanged",
                    issue.id,
                    exc_info=True,
                )
        return state

    async def _flow_route(self, state: FlowState) -> FlowState:
        """Already-satisfied handling + success/failure disposition (gate).

        Reproduces the pre-refactor disposition block exactly:

        * ``already_satisfied`` epic-child / rejected-evidence -> escalate to
          HITL, ``ts_status="escalated"``, stop -> ``done`` (with tail).
        * ``already_satisfied`` closed -> record the ADVANCE verdict inline and
          stop -> ``done`` with ``_skip_tail`` (the old ``return`` posted no
          transcript).
        * success / accepted-with-warnings -> ``ts_status="success"`` and
          continue to ``write-records`` (the former ``_handle_plan_success``,
          now split across ``write-records`` / ``gate`` / ``ready``).
        * plain failure -> ``ts_status="failed"``, stop -> ``done`` (with tail).
        """
        issue = state["issue"]
        result = state["result"]
        adv = state["adv"]

        if result.already_satisfied:
            # Guard: never auto-close epic children as "already satisfied" —
            # they were explicitly created as part of a planned epic and should
            # always get a plan.
            if self._is_epic_child(issue):
                logger.warning(
                    "Issue #%d is an epic child — ignoring "
                    "'already satisfied' claim from planner",
                    issue.id,
                )
                result.already_satisfied = False
                result.success = False
                result.retry_attempted = True
                result.error = (
                    "Planner claimed already satisfied but issue "
                    "is an epic child — escalating to HITL"
                )
                # Clear accumulated adversarial state before HITL hand-off so the
                # next retry starts fresh.
                self._state.clear_adversarial_state(issue.id)
                await self._escalator(
                    issue,
                    cause="Epic child falsely claimed already satisfied",
                    details="Epic child claimed already satisfied",
                    category=FailureCategory.PLAN_VALIDATION,
                )
                state["ts_status"] = "escalated"
                state["_stop"] = True
                return state
            closed = await self._handle_already_satisfied(issue, result)
            if closed:
                record_stage_verdict(
                    self._state,
                    issue_number=issue.id,
                    stage="plan",
                    decision="ADVANCE",
                    signatures=signatures_from_concerns(adv.pending_concerns),
                )
                state["_stop"] = True
                state["_skip_tail"] = True
                return state
            # Evidence validation failed — escalate directly to HITL (do NOT
            # fall through to _handle_plan_failure which would post a second
            # misleading comment). Clear accumulated adversarial state before
            # HITL hand-off so the next retry starts fresh.
            self._state.clear_adversarial_state(issue.id)
            await self._escalator(
                issue,
                cause="Already-satisfied evidence rejected: "
                + "; ".join(result.validation_errors),
                details="; ".join(result.validation_errors),
                category=FailureCategory.PLAN_VALIDATION,
            )
            state["ts_status"] = "escalated"
            state["_stop"] = True
            return state

        if result.success and result.plan:
            state["ts_status"] = "success"
            return state
        if result.retry_attempted and result.plan:
            # Accept the plan despite validation errors — the implementation
            # agent will handle any stale references caused by concurrent
            # changes to the codebase.
            logger.warning(
                "Plan for issue #%d has validation warnings — accepting anyway: %s",
                issue.id,
                "; ".join(result.validation_errors),
            )
            result.success = True
            result.validation_errors = []
            state["ts_status"] = "success"
            return state

        logger.warning(
            "Planning failed for issue #%d — skipping label swap",
            issue.id,
        )
        state["ts_status"] = "failed"
        state["_stop"] = True
        return state

    async def _flow_write_records(self, state: FlowState) -> FlowState:
        """Post the plan + records + adversarial spec stages (pre-gate half).

        Delegates to :meth:`_run_plan_finalization`, which folds the
        touchpoint-expander re-review (ADR-0063 W3b, inside ``_write_plan_records``)
        and the SpecAC/SpecJudge stages. The (possibly decompose-retried) result
        is stashed as ``finalize_result`` for the ready swap; ``result`` (the
        flow's return value / transcript source) is left untouched.
        """
        issue = state["issue"]
        result = state["result"]
        state["finalize_result"] = await self._run_plan_finalization(issue, result)
        return state

    async def _flow_gate(self, state: FlowState) -> FlowState:
        """The #10659 design-decision gate as an explicit node.

        If plan review accumulated >= K design-decision-class CRITICAL concerns
        (unvalidated core mechanism / needs human sign-off — NOT
        implementer-addressable buildability or coverage gaps),
        :meth:`_route_to_hitl_if_design_decision` swaps the issue to
        ``human-required`` and this node stops the walk before ``ready`` (routes
        to ``done``). Runs AFTER all adversarial stages have persisted their
        concerns, so it sees the complete set. Behaviour is identical to the
        pre-refactor inline gate: the ``done`` tail still records the ADVANCE
        verdict + posts the success transcript (``ts_status`` stays ``"success"``).
        """
        issue = state["issue"]
        if await self._route_to_hitl_if_design_decision(issue):
            state["_stop"] = True
        return state

    async def _flow_ready(self, state: FlowState) -> FlowState:
        """Swap to ``hydraflow-ready`` + file discovered sub-issues (post-gate)."""
        issue = state["issue"]
        await self._swap_plan_to_ready(issue, state["finalize_result"])
        return state

    async def _flow_done(self, state: FlowState) -> FlowState:
        """Terminal sink: post the transcript + record the convergence verdict.

        The tail of the pre-refactor ``_plan_one``. Paths that opted out via
        ``_skip_tail`` (shape forks, already-satisfied close) posted no
        transcript / recorded their verdict inline — those skip the tail here.
        """
        if state.get("_skip_tail"):
            return state
        issue = state["issue"]
        result = state["result"]
        adv = state["adv"]
        ts_status = state["ts_status"]
        await self._post_plan_transcript(issue, result, status=ts_status)
        _verdict = _PLAN_VERDICT_MAP.get(ts_status)
        if _verdict is not None:
            record_stage_verdict(
                self._state,
                issue_number=issue.id,
                stage="plan",
                decision=_verdict,
                signatures=signatures_from_concerns(adv.pending_concerns),
            )
        return state

    def _plan_one_with_context(
        self,
        issue: Task,
        gap_guidance: str,
        sibling_plans: dict[int, str],
    ) -> Task:
        """Return a copy of *issue* with gap feedback appended to comments."""
        sibling_summary = "\n\n".join(
            f"### Sibling Issue #{num}\n{plan[:500]}"
            for num, plan in sibling_plans.items()
            if num != issue.id
        )
        extra_comment = (
            f"## Epic Gap Review Feedback\n\n"
            f"{gap_guidance}\n\n"
            f"## Sibling Plan Summaries\n\n"
            f"{sibling_summary}"
        )
        return issue.model_copy(update={"comments": [*issue.comments, extra_comment]})

    async def _post_gap_review_comment(
        self, epic_number: int, review: EpicGapReview, iteration: int
    ) -> None:
        """Post gap review findings as a comment on the epic issue."""
        replan_list = (
            ", ".join(f"#{n}" for n in review.replan_issues)
            if review.replan_issues
            else "None"
        )
        comment = (
            f"## Epic Gap Review (Iteration {iteration})\n\n"
            f"**Findings:**\n{review.findings}\n\n"
            f"**Re-plan required:** {replan_list}\n\n"
            f"**Guidance:**\n{review.guidance}\n\n"
            f"---\n"
            f"*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(epic_number, comment)

    async def _claim_live_epic_replan(
        self,
        epic_number: int,
        issue: Task,
    ) -> Task | None:
        """Reserve *issue* only while both GitHub and the store still own PLAN.

        Gap review retains the cohort's original ``Task`` objects. A child may
        advance to READY or be claimed by implement while the review provider
        is running, so that snapshot cannot authorize another planner. The
        awaited reads establish durable GitHub state; ``try_claim_stage`` is
        the synchronous post-read compare-and-set that closes the local race.
        """
        try:
            live_state, live_labels = await asyncio.gather(
                self._prs.get_issue_state(issue.id),
                self._prs.get_issue_labels(issue.id),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Epic #%d: could not revalidate #%d before re-plan — skipping",
                epic_number,
                issue.id,
                exc_info=True,
            )
            return None

        if str(live_state).upper() != "OPEN":
            logger.info(
                "Epic #%d: skipping re-plan of #%d — live state is %s",
                epic_number,
                issue.id,
                live_state,
            )
            return None

        labels = {str(label).lower() for label in live_labels}
        plan_labels = {label.lower() for label in self._config.planner_label}
        allowed_labels = plan_labels | {
            label.lower() for label in self._config.find_label
        }
        blocking_labels = {
            label.lower() for label in self._config.all_pipeline_labels
        } - allowed_labels
        conflicts = sorted(labels & blocking_labels)
        if not labels.intersection(plan_labels) or conflicts:
            reason = (
                f"conflicting live labels {conflicts}"
                if conflicts
                else "PLAN label is absent"
            )
            logger.info(
                "Epic #%d: skipping re-plan of #%d — %s",
                epic_number,
                issue.id,
                reason,
            )
            return None

        live_issue = issue.model_copy(update={"tags": list(live_labels)})
        if not self._store.try_claim_stage(live_issue, "plan"):
            logger.info(
                "Epic #%d: skipping re-plan of #%d — "
                "local stage or worker ownership changed",
                epic_number,
                issue.id,
            )
            return None
        return live_issue

    async def _plan_epic_group(
        self,
        epic_number: int,
        children: list[Task],
        semaphore: asyncio.Semaphore,
    ) -> list[PlanResult]:
        """Plan all children of an epic with gap review and re-planning."""
        logger.info(
            "Planning epic #%d group (%d children)",
            epic_number,
            len(children),
        )

        # Phase 1: plan all children concurrently
        results = await run_concurrent_batch(
            children,
            lambda idx, issue: self._plan_one(idx, issue, semaphore),
            self._stop_event,
        )

        # Collect successful plans
        plan_map: dict[int, str] = {}
        title_map: dict[int, str] = {}
        issue_map: dict[int, Task] = {c.id: c for c in children}
        for r in results:
            if r.success and r.plan:
                plan_map[r.issue_number] = r.plan
                issue = issue_map.get(r.issue_number)
                title_map[r.issue_number] = issue.title if issue else ""
                r.epic_number = epic_number

        # Skip gap review if fewer than 2 successful plans
        max_iterations = self._config.epic_gap_review_max_iterations
        if len(plan_map) < 2 or max_iterations == 0:
            logger.info(
                "Epic #%d: skipping gap review (%d plans, max_iter=%d)",
                epic_number,
                len(plan_map),
                max_iterations,
            )
            return results

        # Phase 2: gap review loop
        # The gap-review prompt embeds every reviewed child's plan, so the
        # CH-6 prompt gate must see the union of those children's labels
        # (any data-class:<class> elevation on ANY child applies).
        gap_review_labels = sorted(
            {tag for c in children if c.id in plan_map for tag in c.tags}
        )
        for iteration in range(1, max_iterations + 1):
            if self._stop_event.is_set():
                break

            logger.info(
                "Epic #%d: gap review iteration %d/%d",
                epic_number,
                iteration,
                max_iterations,
            )
            transcript = await self._planners.run_gap_review(
                epic_number, plan_map, title_map, issue_labels=gap_review_labels
            )
            review = self._parse_gap_review(transcript, epic_number)

            if not review.replan_issues:
                logger.info(
                    "Epic #%d: plans are coherent after iteration %d",
                    epic_number,
                    iteration,
                )
                break

            await self._post_gap_review_comment(epic_number, review, iteration)

            # Re-plan flagged children with gap context
            eligible_replans = 0
            for issue_number in review.replan_issues:
                if self._stop_event.is_set():
                    break
                issue = issue_map.get(issue_number)
                if issue is None:
                    logger.warning(
                        "Epic #%d: gap review flagged #%d but not in group",
                        epic_number,
                        issue_number,
                    )
                    continue

                live_issue = await self._claim_live_epic_replan(epic_number, issue)
                if live_issue is None:
                    continue

                eligible_replans += 1
                enriched = self._plan_one_with_context(
                    live_issue,
                    review.guidance,
                    plan_map,
                )
                try:
                    replan_result = await self._plan_one(0, enriched, semaphore)
                finally:
                    # _plan_one normally consumes the PLAN reservation through
                    # store_lifecycle. Its early-stop/exception paths may not.
                    # Never release a later READY worker's claim.
                    release_batch_in_flight(
                        self._store,
                        {issue_number},
                        expected_stage="plan",
                    )
                if replan_result.success and replan_result.plan:
                    plan_map[issue_number] = replan_result.plan
                    replan_result.epic_number = epic_number
                # Update the results list
                results = [
                    replan_result if r.issue_number == issue_number else r
                    for r in results
                ]

            if eligible_replans == 0:
                logger.info(
                    "Epic #%d: no requested re-plans remain eligible — "
                    "ending gap review",
                    epic_number,
                )
                break

        return results

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

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

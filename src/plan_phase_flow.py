"""The per-issue plan flow of :class:`plan_phase.PlanPhase` (ADR-0111).

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin; ``PlanPhase`` inherits :class:`PlanFlowMixin`.

One cohesive concern: the explicit ``flows.Flow`` state machine that replaced
the straight-line ``_plan_one`` body, its edge wiring, and every node body —
prepass, surface, draft (the sole LLM actuator), council, route,
write-records, gate, ready, done. The node bodies delegate to the tiering,
prepass, records and disposition mixins; the sequencing lives here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from convergence_recording import record_stage_verdict, signatures_from_concerns
from exception_classify import reraise_on_credit_or_bug
from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from harness_insights import FailureCategory
from models import DiscoverResult, PlanResult, Task
from pending_concerns import AdversarialState
from phase_utils import _sentry_transaction, store_lifecycle
from plan_phase_common import _PLAN_VERDICT_MAP, _flow_stopped

if TYPE_CHECKING:
    from adversarial_agents import AgentLike
    from config import HydraFlowConfig
    from models import ShapeTurnResult
    from phase_utils import PipelineEscalator
    from plan_constants import PlanScale
    from planner import PlannerRunner
    from ports import IssueStorePort, PRPort
    from research_runner import ResearchRunner
    from state import StateTracker
    from task_source import TaskTransitioner

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


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


class PlanFlowMixin:
    """The per-issue plan flow of :class:`plan_phase.PlanPhase` (ADR-0111)."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _council_agents: dict[str, AgentLike] | None
    _escalator: PipelineEscalator
    _planners: PlannerRunner
    _prs: PRPort
    _research_runner: ResearchRunner | None
    _state: StateTracker
    _stop_event: asyncio.Event
    _store: IssueStorePort
    _surfacer_agent: AgentLike | None
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        def _forced_plan_scale(
            self, issue: Task
        ) -> PlanScale | None: ...  # provided by PlanTieringMixin

        async def _handle_already_satisfied(
            self, issue: Task, result: PlanResult
        ) -> bool: ...  # provided by PlanDispositionMixin

        def _has_priority_label(
            self, issue: Task
        ) -> bool: ...  # provided by PlanTieringMixin

        def _is_epic_child(self, issue: Task) -> bool: ...  # provided by PlanEpicMixin

        def _is_memory_backlog_issue(
            self, issue: Task
        ) -> bool: ...  # provided by PlanTieringMixin

        async def _post_plan_transcript(
            self, issue: Task, result: PlanResult, *, status: str
        ) -> None: ...  # provided by PlanDispositionMixin

        async def _route_light_lane(
            self, issue: Task, state: FlowState
        ) -> bool: ...  # provided by PlanTieringMixin

        async def _route_to_hitl_if_design_decision(
            self, issue: Task
        ) -> bool: ...  # provided by PlanDispositionMixin

        async def _run_assumption_surfacer(
            self, issue: Task, adv: AdversarialState, research_context: str
        ) -> None: ...  # provided by PlanAdversarialMixin

        async def _run_discover_helper(
            self, issue: Task, *, guidance: str
        ) -> DiscoverResult | None: ...  # provided by PlanPrepassMixin

        async def _run_plan_council(
            self, issue: Task, adv: AdversarialState, plan_text: str
        ) -> None: ...  # provided by PlanAdversarialMixin

        async def _run_plan_finalization(
            self, issue: Task, result: PlanResult
        ) -> PlanResult: ...  # provided by PlanRecordsMixin

        async def _run_shape_helper(
            self, issue: Task, discover_result: DiscoverResult, *, guidance: str
        ) -> ShapeTurnResult | None: ...  # provided by PlanPrepassMixin

        def _should_discover_helper(
            self, issue: Task
        ) -> bool: ...  # provided by PlanPrepassMixin

        def _should_research(
            self, issue: Task
        ) -> bool: ...  # provided by PlanPrepassMixin

        def _should_shape_helper(
            self, issue: Task, discover_result: DiscoverResult | None
        ) -> bool: ...  # provided by PlanPrepassMixin

        def _skip_plan_review(
            self, issue: Task
        ) -> tuple[bool, int]: ...  # provided by PlanTieringMixin

        async def _swap_plan_to_ready(
            self, issue: Task, result: PlanResult
        ) -> None: ...  # provided by PlanDispositionMixin

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

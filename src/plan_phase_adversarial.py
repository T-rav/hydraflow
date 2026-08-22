"""Adversarial plan stages of :class:`plan_phase.PlanPhase`.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``plan_phase_wiki_ingest.py`` from #10840.
``PlanPhase`` inherits :class:`PlanAdversarialMixin`, so the class keeps ONE
identity in ``plan_phase``.

One cohesive concern: the ADR-0064 earlier-adversarial pipeline as it applies
to a plan — wiring the four optional agents, persisting the shared
``AdversarialState``, and running stages 1 (AssumptionSurfacer), 3
(PlanCouncil tight loop) and 5+6 (SpecAC draft + SpecJudge).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from adversarial_agents import AgentLike
from adversarial_retry_loop import AdversarialRetryLoop
from assumption_surfacer import AssumptionSurfacer, SurfacerOutput
from models import Task
from pending_concerns import AdversarialState, StageRun
from plan_council import CouncilTally, PlanCouncil
from spec_ac_generator import SpecACGenerator
from spec_judge import JudgeResult, SpecJudge

if TYPE_CHECKING:
    from events import EventBus
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


class PlanAdversarialMixin:
    """Adversarial plan stages of :class:`plan_phase.PlanPhase`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _adversarial_budget: int
    _bus: EventBus
    _council_agents: dict[str, AgentLike] | None
    _spec_ac_agent: AgentLike | None
    _spec_judge_agent: AgentLike | None
    _state: StateTracker
    _surfacer_agent: AgentLike | None

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

"""Plan-retry self-solver — the give-up→decompose/diagnose terminal (#10735).

When the plan-retry give-up window is exhausted (``N`` blocking-review
route-backs within ``T``), the :class:`route_back.RouteBackCoordinator` calls
this :class:`~giveup_window.SelfSolver` instead of routing the issue back to
PLAN yet again — and, critically, instead of routing it to ``human-required``.

The ladder, reusing existing machinery rather than inventing an escalation:

  1. **Decompose (ADR-0105).** Run ``preflight.decompose_terminal.
     decompose_or_escalate`` — the same terminal the auto-agent uses at its
     attempt cap. On success the non-convergent issue is superseded by an epic
     of convergent children and ``human-required`` is never applied.
  2. **Diagnose.** If the decompose council declines (or decompose isn't
     wired / depth-capped), fall back to the auto-agent diagnose label so the
     diagnose path can resolve-or-dismiss with evidence — still a machine move.
  3. **Exhausted.** Only if both are unavailable does the coordinator apply
     ``human-required`` (last resort, logged as a break).

This adapter owns only steps 1–2; the coordinator owns step 3. Kept out of
``route_back`` so the coordinator stays free of the epic/decomposer/council
imports and remains a small, pure state-machine primitive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from exception_classify import reraise_on_credit_or_bug
from giveup_window import SelfSolveOutcome
from preflight.context import PreflightContext
from preflight.decompose_terminal import DECOMPOSED, decompose_or_escalate

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from decomposition_council import DecompositionCouncil
    from issue_decomposer import IssueDecomposer
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.giveup_self_solve")

__all__ = ["PlanRetrySelfSolver"]


class PlanRetrySelfSolver:
    """Runs the ADR-0105 decompose terminal, diagnose as the fallback."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRPort,
        decomposer: IssueDecomposer | None,
        council: DecompositionCouncil | None,
        diagnose_label: str = "",
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._decomposer = decomposer
        self._council = council
        self._diagnose_label = diagnose_label

    async def solve(
        self, issue_id: int, *, from_stage: str, reason: str, issue_body: str = ""
    ) -> SelfSolveOutcome:
        """Attempt decompose, then diagnose; return the action that fired.

        Never raises for ordinary failures (the caller applies human-required
        on ``EXHAUSTED``), but a credit-exhaustion / real-bug exception is
        re-raised via :func:`reraise_on_credit_or_bug` so the loop's global
        pause/bug signal is not silently eaten.
        """
        ctx = PreflightContext(
            issue_number=issue_id,
            issue_body=issue_body,
            issue_comments=[],
            sub_label="plan-retry",
            escalation_context=None,
            wiki_excerpts="",
            sentry_events=[],
            recent_commits=[],
        )

        # Step 1: decompose (ADR-0105). decompose_or_escalate returns
        # "decomposed" on success or "human-required" when the council declines,
        # decompose isn't wired, or the depth cap is spent.
        try:
            outcome = await decompose_or_escalate(
                issue_number=issue_id,
                ctx=ctx,
                config=self._config,
                decomposer=self._decomposer,
                council=self._council,
                state=self._state,
                # decompose_or_escalate's private _PRPort duck-types close_pr as
                # `-> None`; PRPort returns bool (benign here — the return is
                # ignored). Cast mirrors AutoAgentPreflightLoop's `Any` prs.
                prs=cast("Any", self._prs),
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "give-up self-solve: decompose terminal raised for issue #%d "
                "— falling back to diagnose: %s",
                issue_id,
                exc,
                exc_info=True,
            )
            outcome = "human-required"

        if outcome == DECOMPOSED:
            return SelfSolveOutcome.DECOMPOSED

        # Step 2: diagnose fallback. Route to the auto-agent diagnose stage for
        # one more autonomous resolve-or-dismiss pass before any human.
        if self._diagnose_label:
            try:
                await self._prs.swap_pipeline_labels(issue_id, self._diagnose_label)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "give-up self-solve: diagnose label swap failed for issue "
                    "#%d — self-solve exhausted: %s",
                    issue_id,
                    exc,
                )
                return SelfSolveOutcome.EXHAUSTED
            logger.info(
                "Issue #%d give-up window: decompose declined, routed to "
                "diagnose (%s) for autonomous triage",
                issue_id,
                self._diagnose_label,
            )
            return SelfSolveOutcome.DIAGNOSED

        # Neither decompose nor diagnose available — the coordinator applies
        # human-required (last resort).
        return SelfSolveOutcome.EXHAUSTED

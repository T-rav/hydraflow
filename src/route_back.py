"""Route-back coordinator — pipeline state-machine route-back primitive (#6423).

When a precondition gate fails (``stage_preconditions.check_preconditions``
returns not-ok), the affected issue must NOT be silently dropped from
the work queue. Instead, it gets routed back to its previous stage with
the failure reason as feedback context, so the upstream phase can fix
its output and try again.

This module provides ``RouteBackCoordinator``, a small coordinator that
ties together the four things a route-back has to do:

  1. **Swap pipeline labels** on the GitHub issue (e.g. ``hydraflow-ready``
     → ``hydraflow-plan``) so the upstream phase will pick it up next
     cycle.
  2. **Write a structured ``route_back`` record** to the issue cache so
     the audit trail and the upstream phase can read the feedback context.
  3. **Increment a per-issue route-back counter**, persisted via the
     state tracker so the counter survives restarts.
  4. **Escalate to HITL** when the counter exceeds ``max_route_backs`` —
     prevents an issue from oscillating between stages forever.

The coordinator is independent of any specific phase: ``plan_phase``,
``implement_phase``, and ``review_phase`` all call the same
``route_back()`` method with their stage labels. This keeps the routing
policy in one place.

Companion to ``stage_preconditions``, ``IssueCache``, and ``PRPort``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from exception_classify import reraise_on_credit_or_bug
from giveup_window import SelfSolveOutcome

if TYPE_CHECKING:
    from giveup_window import GiveUpTracker, GiveUpWindow, SelfSolver
    from issue_cache import IssueCache
    from ports import PRPort

logger = logging.getLogger("hydraflow.route_back")

__all__ = [
    "RouteBackCoordinator",
    "RouteBackCounterPort",
    "RouteBackOutcome",
    "RouteBackResult",
]


class RouteBackOutcome(StrEnum):
    """The disposition of a route-back attempt."""

    # The issue was routed back to the upstream stage; the counter is
    # below the cap and the upstream phase will pick it up next cycle.
    ROUTED = "routed"
    # The route-back counter exceeded ``max_route_backs``; the issue
    # was escalated to HITL instead of being routed back again.
    ESCALATED = "escalated"
    # The give-up window (N-in-T) was exhausted and the issue was routed
    # to a machine self-solve (ADR-0105 decompose, or the auto-agent
    # diagnose path) — NOT to a human. Also covers the terminal finding
    # the fix already landed (#11480): nothing to route, the issue closes
    # with its fix. This is the give-up→self-solve terminal (#10735);
    # ``human-required`` is applied only when the self-solve path itself
    # exhausts (which returns ESCALATED, logged as a break).
    SELF_SOLVED = "self_solved"
    # An unexpected failure during the route-back itself (label swap
    # raised, cache write raised). Logged at warning, returned for
    # caller awareness — the issue stays in its current state.
    FAILED = "failed"


class RouteBackResult:
    """Outcome of a route-back attempt + the new counter value."""

    __slots__ = ("outcome", "counter", "reason")

    def __init__(
        self,
        outcome: RouteBackOutcome,
        counter: int,
        reason: str = "",
    ) -> None:
        self.outcome = outcome
        self.counter = counter
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"RouteBackResult(outcome={self.outcome}, "
            f"counter={self.counter}, reason={self.reason!r})"
        )


@runtime_checkable
class RouteBackCounterPort(Protocol):
    """Port for the per-issue route-back counter store.

    Lets the coordinator stay decoupled from ``StateTracker`` so it
    can be tested with a tiny in-memory dict implementation. The full
    StateTracker integration lives in the phase wiring follow-up.
    """

    def get_route_back_count(self, issue_id: int) -> int:
        """Return the current route-back count for *issue_id*."""
        ...

    def increment_route_back_count(self, issue_id: int) -> int:
        """Increment and return the new route-back count for *issue_id*."""
        ...

    def decrement_route_back_count(self, issue_id: int) -> int:
        """Decrement and return the new route-back count for *issue_id*.

        Used by the coordinator to undo an increment when a label swap
        fails after the counter was already incremented — without this
        rollback, transient ``gh`` network blips would burn through the
        route-back budget without any actual route-back happening.

        Must be a no-op (return 0) when the counter is already at 0.
        """
        ...


class RouteBackCoordinator:
    """Coordinates label swap + cache record + counter + escalation.

    Escalation chain when ``max_route_backs`` is exceeded:

      1. Try to swap to ``diagnose_label`` first. The diagnostic stage
         runs an automated diagnostic agent that triages the failure
         (reads recent transcripts, classifies the root cause, and
         either re-queues the issue with feedback or hands it to HITL).
         This matches the existing :class:`PipelineEscalator` pattern
         and gives the pipeline one more autonomous shot at recovering
         before requiring a human.
      2. If the diagnose label swap fails (or no ``diagnose_label`` was
         configured), fall back to swapping the ``hitl_label`` directly.
      3. If the HITL swap also fails, the result is ``FAILED`` and the
         issue stays in its current stage for the next cycle to retry.

    A direct-to-HITL coordinator (no diagnose stage) can be built by
    passing ``diagnose_label=""``.
    """

    def __init__(
        self,
        *,
        cache: IssueCache,
        prs: PRPort,
        counter: RouteBackCounterPort,
        hitl_label: str,
        diagnose_label: str = "",
        max_route_backs: int = 2,
        give_up_tracker: GiveUpTracker | None = None,
        plan_retry_window: GiveUpWindow | None = None,
        self_solve: SelfSolver | None = None,
        human_required_label: str = "human-required",
    ) -> None:
        """Build the coordinator.

        ``hitl_label`` is the GitHub label applied as the final-fallback
        escalation target (e.g. ``"hydraflow-hitl"``).

        ``diagnose_label`` is the intermediate escalation target tried
        BEFORE HITL when the counter exceeds the cap. Default empty
        string disables the diagnose hop and goes straight to HITL.
        Operators should pass ``config.diagnose_label[0]`` to match
        the existing :class:`PipelineEscalator` behavior.

        ``max_route_backs`` is the soft cap — once an issue has been
        routed back this many times, the next route-back attempt
        escalates instead.

        **Give-up window mode (#10735).** When ``give_up_tracker`` and
        ``plan_retry_window`` are both supplied, the monotonic
        ``max_route_backs`` cap is superseded by a formal ``N``-in-``T``
        restart-intensity window: the terminal fires only when ``N``
        route-backs land within ``T`` seconds (so convergent retries that
        DO settle within the window are never escalated). On exhaustion the
        issue is routed to ``self_solve`` — a machine self-solve (ADR-0105
        decompose / auto-agent diagnose), NOT ``human-required``. Human is
        applied only if the self-solve path itself exhausts. When the window
        is not supplied the coordinator keeps its exact legacy behaviour.
        """
        self._cache = cache
        self._prs = prs
        self._counter = counter
        self._hitl_label = hitl_label
        self._diagnose_label = diagnose_label
        self._max_route_backs = max_route_backs
        self._give_up_tracker = give_up_tracker
        self._plan_retry_window = plan_retry_window
        self._self_solve = self_solve
        self._human_required_label = human_required_label

    @property
    def max_route_backs(self) -> int:
        return self._max_route_backs

    @property
    def give_up_window_active(self) -> bool:
        """True when the N-in-T give-up window supersedes the monotonic cap."""
        return self._give_up_tracker is not None and self._plan_retry_window is not None

    def reset_window(self, issue_id: int) -> None:
        """Clear *issue_id*'s plan-retry give-up window — call on convergence.

        No-op when the window is not active. The precondition gate calls this
        for every issue that PASSES its stage preconditions, so an issue that
        converges within the window starts fresh and never carries stale
        restart-intensity toward a spurious self-solve.
        """
        if self._give_up_tracker is not None and self._plan_retry_window is not None:
            self._give_up_tracker.reset(issue_id, self._plan_retry_window)

    async def route_back(
        self,
        issue_id: int,
        *,
        from_stage: str,
        to_stage: str,
        reason: str,
        feedback_context: str = "",
        issue_body: str = "",
    ) -> RouteBackResult:
        """Route *issue_id* from ``from_stage`` back to ``to_stage``.

        Returns a :class:`RouteBackResult` describing the outcome:

        - ``ROUTED``: the issue was routed back; the upstream phase
          will pick it up on its next cycle. The cache has a
          ``route_back`` record with the feedback context.
        - ``ESCALATED``: the counter is now above ``max_route_backs``;
          the issue was labeled HITL instead of being routed back
          again. The cache record still gets written so the audit
          trail records the attempted route-back.
        - ``FAILED``: an exception fired during the label swap or
          cache write. The issue is left in its current state and
          the caller can retry next cycle.

        The counter is incremented before the cap check, so the very
        first route-back gets count=1; ``max_route_backs=2`` means the
        third attempt escalates.
        """
        try:
            new_count = self._counter.increment_route_back_count(issue_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: counter increment failed for issue #%d: %s",
                issue_id,
                exc,
            )
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=0,
                reason=f"counter increment failed: {exc}",
            )

        # Always record the route-back attempt in the audit trail —
        # whether it advances or escalates, the upstream phase needs
        # to see the feedback context on the next cycle.
        try:
            self._cache.record_route_back(
                issue_id,
                from_stage=from_stage,
                to_stage=to_stage,
                reason=reason,
                feedback_context=feedback_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: cache write failed for issue #%d: %s",
                issue_id,
                exc,
            )
            # Cache write is best-effort — proceed with the label swap
            # even if the audit trail couldn't be persisted. Phase code
            # already logs failures via the cache module itself.

        # Decide whether this route-back escalates. Two mutually-exclusive
        # policies: the formal N-in-T give-up window (#10735) when wired,
        # otherwise the legacy monotonic ``max_route_backs`` cap.
        report_count = new_count
        threshold = self._max_route_backs
        if self._give_up_tracker is not None and self._plan_retry_window is not None:
            # Give-up window mode: record this route-back as a restart-intensity
            # event and, if N landed within T, route to a machine self-solve
            # (decompose/diagnose) instead of routing back again. A count still
            # below N is convergent retry — untouched.
            report_count = self._give_up_tracker.record_and_count(
                issue_id, self._plan_retry_window
            )
            threshold = self._plan_retry_window.max_restarts
            if self._plan_retry_window.is_exhausted(report_count):
                return await self._self_solve_terminal(
                    issue_id,
                    from_stage=from_stage,
                    reason=reason,
                    counter=report_count,
                    issue_body=issue_body,
                )
        elif new_count > self._max_route_backs:
            # Legacy monotonic cap exceeded — escalate to diagnose/HITL.
            return await self._escalate(
                issue_id,
                from_stage=from_stage,
                reason=reason,
                counter=new_count,
            )

        # Under the cap/window — perform the label swap and return ROUTED.
        try:
            await self._prs.swap_pipeline_labels(issue_id, to_stage)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: label swap failed for issue #%d: %s",
                issue_id,
                exc,
            )
            # Undo the counter increment — the label swap was the
            # action being counted, and it didn't happen. Without
            # this rollback, two consecutive label-swap failures
            # (e.g. transient `gh` network blips) would burn through
            # the route-back budget and trigger spurious HITL escalation.
            try:
                rolled_back = self._counter.decrement_route_back_count(issue_id)
            except Exception as decrement_exc:  # noqa: BLE001
                logger.warning(
                    "route_back: counter rollback failed for issue #%d: %s",
                    issue_id,
                    decrement_exc,
                )
                rolled_back = new_count
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=rolled_back,
                reason=f"label swap failed: {exc}",
            )

        logger.info(
            "Issue #%d routed back %s → %s (count=%d/%d): %s",
            issue_id,
            from_stage,
            to_stage,
            report_count,
            threshold,
            reason,
        )
        return RouteBackResult(
            RouteBackOutcome.ROUTED,
            counter=report_count,
            reason=reason,
        )

    async def _self_solve_terminal(
        self,
        issue_id: int,
        *,
        from_stage: str,
        reason: str,
        counter: int,
        issue_body: str = "",
    ) -> RouteBackResult:
        """Give-up window exhausted → self-solve, human only as last resort.

        Escalation ladder (ADR-0105; #10735 corrected routing):

          1. ``self_solve`` runs the ADR-0105 decompose terminal — split the
             non-convergent issue into convergent children. If it decomposes,
             the issue is superseded by an epic and ``human-required`` is never
             applied (``SELF_SOLVED``).
          2. If decompose declines, the self-solver falls back to the
             auto-agent diagnose path (``SELF_SOLVED``) — still a machine move.
             If instead the terminal finds the fix already landed
             (``ALREADY_SATISFIED``, #11480) there is nothing to route: no
             relabel at all, the issue closes with its fix (``SELF_SOLVED``).
          3. Only if the self-solve path itself exhausts (``EXHAUSTED``) is
             ``human-required`` applied — a rare event, logged as a break at
             WARNING. Routing a convergence-solvable issue straight to a human
             is the HITL-scatter anti-pattern this window fixes.
        """
        outcome = SelfSolveOutcome.EXHAUSTED
        if self._self_solve is not None:
            try:
                outcome = await self._self_solve.solve(
                    issue_id,
                    from_stage=from_stage,
                    reason=reason,
                    issue_body=issue_body,
                )
            except Exception as exc:  # noqa: BLE001
                # The self-solver spawns subprocess work (the decompose
                # terminal's `gh` reads and the council/decomposer runs), so
                # this is a subprocess-runner handler and owes the standing
                # reraise. ``PlanRetrySelfSolver.solve`` documents that it
                # re-raises credit-exhaustion / real-bug exceptions rather
                # than eating them; without the same call here that contract
                # died one frame up — the billing signal was logged as a
                # warning and converted into EXHAUSTED → human-required,
                # burning attempt budget against an exhausted account and
                # hiding genuine TypeError/KeyError bugs in the give-up path
                # behind a "self-solve exhausted" line (#11609).
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "route_back: self-solve raised for issue #%d — treating as "
                    "exhausted (human-required): %s",
                    issue_id,
                    exc,
                )
                outcome = SelfSolveOutcome.EXHAUSTED

        # Record which self-solve action fired for the /api give-up surface.
        if self._give_up_tracker is not None and self._plan_retry_window is not None:
            self._give_up_tracker.record_action(
                issue_id, self._plan_retry_window, outcome
            )

        if outcome in (
            SelfSolveOutcome.DECOMPOSED,
            SelfSolveOutcome.DIAGNOSED,
            SelfSolveOutcome.ALREADY_SATISFIED,
        ):
            logger.info(
                "Issue #%d give-up window exhausted after %d plan-retries — "
                "self-solved via %s (no human)",
                issue_id,
                counter,
                outcome.value,
            )
            return RouteBackResult(
                RouteBackOutcome.SELF_SOLVED,
                counter=counter,
                reason=(
                    f"give-up window exhausted after {counter} plan-retries; "
                    f"self-solved via {outcome.value}"
                ),
            )

        # Self-solve exhausted — human-required is the last resort. Logged as a
        # break so an operator can see the rare case the machine couldn't route.
        logger.warning(
            "BREAK: issue #%d self-solve exhausted after give-up window "
            "(%d plan-retries) — routing to human-required (last resort): %s",
            issue_id,
            counter,
            reason,
        )
        try:
            await self._prs.swap_pipeline_labels(issue_id, self._human_required_label)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: human-required escalation label swap failed for "
                "issue #%d: %s",
                issue_id,
                exc,
            )
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=counter,
                reason=f"human-required escalation label swap failed: {exc}",
            )
        return RouteBackResult(
            RouteBackOutcome.ESCALATED,
            counter=counter,
            reason=(
                f"give-up window exhausted after {counter} plan-retries; "
                f"self-solve exhausted — human-required (last resort): {reason}"
            ),
        )

    async def _escalate(
        self,
        issue_id: int,
        *,
        from_stage: str,
        reason: str,
        counter: int,
    ) -> RouteBackResult:
        """Escalate via diagnose stage first, HITL as fallback.

        Tries the ``diagnose_label`` swap first when one is configured.
        The diagnostic stage runs an automated diagnostic agent that
        triages the failure and either re-queues the issue with
        feedback or hands it off to HITL — one more autonomous shot
        at recovery before requiring a human.

        Falls back to ``hitl_label`` directly if the diagnose swap
        fails or no diagnose label was configured. If the HITL swap
        also fails, returns ``FAILED`` so the next cycle can retry.
        """
        # Try diagnose stage first when configured.
        if self._diagnose_label:
            try:
                await self._prs.swap_pipeline_labels(issue_id, self._diagnose_label)
                escalation_reason = (
                    f"route-back cap exceeded after {counter} attempts "
                    f"(max={self._max_route_backs}); last reason from "
                    f"{from_stage}: {reason} — escalated to diagnose for "
                    f"automated triage before HITL"
                )
                logger.warning(
                    "Issue #%d escalated to DIAGNOSE after %d route-backs: %s",
                    issue_id,
                    counter,
                    reason,
                )
                return RouteBackResult(
                    RouteBackOutcome.ESCALATED,
                    counter=counter,
                    reason=escalation_reason,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "route_back: diagnose escalation failed for issue #%d, "
                    "falling back to HITL: %s",
                    issue_id,
                    exc,
                )

        # Fallback (or no diagnose configured): direct HITL swap.
        try:
            await self._prs.swap_pipeline_labels(issue_id, self._hitl_label)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "route_back: HITL escalation label swap failed for issue #%d: %s",
                issue_id,
                exc,
            )
            return RouteBackResult(
                RouteBackOutcome.FAILED,
                counter=counter,
                reason=f"escalation label swap failed: {exc}",
            )

        escalation_reason = (
            f"route-back cap exceeded after {counter} attempts "
            f"(max={self._max_route_backs}); last reason from "
            f"{from_stage}: {reason}"
        )
        logger.warning(
            "Issue #%d escalated to HITL after %d route-backs: %s",
            issue_id,
            counter,
            reason,
        )
        return RouteBackResult(
            RouteBackOutcome.ESCALATED,
            counter=counter,
            reason=escalation_reason,
        )

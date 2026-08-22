"""HITL and human-steering surface of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorHITLMixin`.

One cohesive concern: the channel a human uses to reach a running factory —
the dashboard-facing HITL question/answer/correction verbs, and the ADR-0103
steering actuator that reads the persisted ``SteeringState`` and enacts the
pause / abort / redo decision computed by ``human_steering.apply_steering``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from human_steering import apply_steering, resolve_redo_phase
from issue_store import STAGE_NAME_MAP, IssueStoreStage
from models import SteeringState
from phase_utils import escalate_to_hitl

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from hitl_controller import HITLController
    from issue_store import IssueStore
    from service_registry import ServiceRegistry
    from state import StateTracker


class OrchestratorHITLMixin:
    """HITL and human-steering surface of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _hitl_ctrl: HITLController
    _state: StateTracker
    _svc: ServiceRegistry

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

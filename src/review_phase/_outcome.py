"""Approved / rejected review routing of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: the terminal branch of a review — taking a decided verdict and
carrying out its consequence, either through the convergence gate on the
approve path or the reject route that re-queues, escalates, or stops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import review_phase
from harness_insights import FailureCategory
from models import HitlEscalation, PipelineStage

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any

    from config import HydraFlowConfig
    from convergence_gate import GateResult
    from harness_insights import HarnessInsightStore
    from models import (
        CodeScanningAlert,
        PRInfo,
        ReviewResult,
        Task,
        VisualValidationDecision,
    )
    from phase_utils import MemorySuggester
    from ports import IssueStorePort
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.review_phase")


class ReviewOutcomeMixin:
    """Approved / rejected review routing of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _harness_insights: HarnessInsightStore | None
    _state: StateTracker
    _store: IssueStorePort
    _suggest_memory: MemorySuggester
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        async def _convergence_decision(
            self,
            *,
            issue_number: int,
            review_approved: bool,
            code_scanning_alerts: list[Any] | None = None,
            post_verify_judge: Callable[..., Any] | None = None,
            reject_review_result: Any | None = None,
        ) -> GateResult: ...  # provided by _judge

        async def _escalate_to_hitl(
            self, esc: HitlEscalation
        ) -> None: ...  # provided by _insights

        async def _handle_approved_merge(
            self,
            pr: PRInfo,
            issue: Task,
            result: ReviewResult,
            diff: str,
            worker_id: int,
            code_scanning_alerts: list[CodeScanningAlert] | None = None,
            visual_decision: VisualValidationDecision | None = None,
        ) -> None: ...  # provided by _self_fix

        def _post_verify_lens_judge(
            self,
            *,
            pr: Any,
            task: Any,
            wt_path: Any,
            result: Any,
            diff: str,
            worker_id: int,
            surface: str,
        ) -> Callable[..., Any]: ...  # provided by _judge

        async def _publish_review_status(
            self, pr: PRInfo, worker_id: int, status: str
        ) -> None: ...  # provided by _insights

    async def _handle_rejected_review(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Handle REQUEST_CHANGES or COMMENT verdict via the convergence gate.

        Delegates unconditionally to ``_handle_rejected_review_gated``. The
        gate is always-on; the legacy retry-vs-escalate path is removed.

        Returns *True* if the worktree should be preserved (loop-back case),
        *False* if the worktree should be destroyed (HITL escalation).
        """
        return await self._handle_rejected_review_gated(pr, task, result, worker_id)

    async def _handle_rejected_review_gated(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Convergence-gate reject/escalate decision (unconditional, sole path).

        The review verdict is REQUEST_CHANGES/COMMENT here
        (``review_approved=False``), so the gate's deterministic check is RED:
        it loops back (re-queue to ``ready``) until the outer lap budget is
        exhausted, at which point it escalates to HITL.
        """
        from convergence_gate import GateDecision  # noqa: PLC0415

        decision = await self._convergence_decision(
            issue_number=pr.issue_number,
            review_approved=False,
            reject_review_result=result,
        )

        if decision.decision is GateDecision.LOOP_BACK:
            # Under cap: re-queue for implementation with feedback.
            self._state.set_review_feedback(
                pr.issue_number, decision.feedback or result.summary
            )
            self._store.enqueue_transition(task, "ready")
            await self._transitioner.transition(
                pr.issue_number, "ready", pr_number=pr.number
            )
            await self._transitioner.post_comment(
                pr.issue_number,
                "**Review requested changes** — re-queuing for "
                "implementation with feedback.",
            )
            logger.info(
                "PR #%d: %s verdict — convergence loop-back, re-queuing issue #%d",
                pr.number,
                result.verdict.value,
                pr.issue_number,
            )
            return True  # Preserve worktree

        # ESCALATE
        ledger = self._state.get_convergence_ledger(pr.issue_number)
        oscillating = bool(ledger and ledger.detect_outer_oscillation())
        cause = (
            "review convergence oscillation — same findings recurred across laps"
            if oscillating
            else (decision.reason or "review convergence cap exceeded")
        )
        logger.warning(
            "PR #%d: review convergence escalation (%s) — escalating issue #%d to HITL",
            pr.number,
            cause,
            pr.issue_number,
        )
        review_phase.record_harness_failure(
            self._harness_insights,
            pr.issue_number,
            FailureCategory.HITL_ESCALATION,
            cause,
            stage=PipelineStage.REVIEW,
            pr_number=pr.number,
        )
        await self._publish_review_status(pr, worker_id, "escalating")
        from models import EscalationContext  # noqa: PLC0415

        esc_context = EscalationContext(
            cause=cause,
            origin_phase="review",
            pr_number=pr.number,
            agent_transcript=result.transcript if result.transcript else None,
        )
        self._state.set_escalation_context(pr.issue_number, esc_context)
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=pr.issue_number,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**Review convergence escalation** — {cause}. "
                    f"Escalating to human review."
                ),
                post_on_pr=False,
                event_cause="review_convergence_escalation",
                task=task,
            )
        )
        # Reset the outer lap budget so a human-fixed, re-queued issue can
        # loop back through the gate rather than insta-re-escalating (F2).
        self._state.reset_outer_laps(pr.issue_number)
        if result.transcript:
            await self._suggest_memory(
                result.transcript,
                "review_convergence_escalation",
                f"PR #{pr.number}",
            )
        return False  # Destroy worktree

    async def _handle_approved_review_gated(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        *,
        surface: str,
        code_scanning_alerts: list[CodeScanningAlert] | None,
        visual_decision: VisualValidationDecision | None,
    ) -> bool:
        """Convergence-gate APPROVE decision (unconditional, sole path).

        Called when the review verdict is APPROVE. Builds the real lens judge
        and routes through :meth:`_convergence_decision` with
        ``review_approved=True``:

        * **ADVANCE** → ``_handle_approved_merge`` (the recorded
          ``last_verdict == "ADVANCE"`` makes ``recompute_converged`` flip
          ``ledger.converged`` to True inside ``_convergence_decision`` via
          ``recompute_converged``, BEFORE control returns here). Worktree
          destroyed.
        * **LOOP_BACK** → re-queue to ``ready`` with the gate feedback,
          mirroring the reject loop-back contract. Worktree preserved.
        * **ESCALATE** → HITL. Worktree destroyed.

        Returns the ``skip_worktree_cleanup`` flag: True to preserve the
        worktree (loop-back), False to destroy it (advance/escalate).
        """
        from convergence_gate import GateDecision  # noqa: PLC0415

        judge = self._post_verify_lens_judge(
            pr=pr,
            task=task,
            wt_path=wt_path,
            result=result,
            diff=diff,
            worker_id=worker_id,
            surface=surface,
        )
        decision = await self._convergence_decision(
            issue_number=pr.issue_number,
            review_approved=True,
            code_scanning_alerts=code_scanning_alerts,
            post_verify_judge=judge,
        )

        if decision.decision is GateDecision.ADVANCE:
            await self._handle_approved_merge(
                pr,
                task,
                result,
                diff,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
                visual_decision=visual_decision,
            )
            return False  # Destroy worktree

        if decision.decision is GateDecision.LOOP_BACK:
            self._state.set_review_feedback(
                pr.issue_number, decision.feedback or result.summary
            )
            self._store.enqueue_transition(task, "ready")
            await self._transitioner.transition(
                pr.issue_number, "ready", pr_number=pr.number
            )
            await self._transitioner.post_comment(
                pr.issue_number,
                "**Convergence gate requested changes** — "
                "re-queuing for implementation.",
            )
            logger.info(
                "PR #%d: approve-gate loop-back — re-queuing issue #%d",
                pr.number,
                pr.issue_number,
            )
            return True  # Preserve worktree

        # ESCALATE
        cause = decision.reason or "approve-gate escalation"
        logger.warning(
            "PR #%d: approve-gate escalation (%s) — escalating issue #%d to HITL",
            pr.number,
            cause,
            pr.issue_number,
        )
        review_phase.record_harness_failure(
            self._harness_insights,
            pr.issue_number,
            FailureCategory.HITL_ESCALATION,
            cause,
            stage=PipelineStage.REVIEW,
            pr_number=pr.number,
        )
        await self._publish_review_status(pr, worker_id, "escalating")
        from models import EscalationContext  # noqa: PLC0415

        esc_context = EscalationContext(
            cause=cause,
            origin_phase="review",
            pr_number=pr.number,
            agent_transcript=result.transcript if result.transcript else None,
        )
        self._state.set_escalation_context(pr.issue_number, esc_context)
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=pr.issue_number,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**Convergence gate escalation.** {cause}. "
                    f"Escalating to human review."
                ),
                post_on_pr=False,
                event_cause="review_convergence_escalation",
                task=task,
            )
        )
        # Reset the outer lap budget so a human-fixed, re-queued issue can
        # loop back through the gate rather than insta-re-escalating (F2).
        self._state.reset_outer_laps(pr.issue_number)
        if result.transcript:
            await self._suggest_memory(
                result.transcript,
                "review_convergence_escalation",
                f"PR #{pr.number}",
            )
        return False  # Destroy worktree

"""Convergence gate and post-verify lens judge of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: deciding whether a review has *converged* (ADR-0094–0098) — which
lenses a given pass runs, the deterministic approve check, the lens judge that
turns a post-verify advisor result into a verdict, and the gate decision that
routes ADVANCE / LOOP_BACK / ESCALATE.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from convergence_recording import _normalize_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import HydraFlowConfig
    from convergence_gate import DetResult, GateResult
    from review_advisor import PostVerifyResult, ReviewPlan
    from state import StateTracker

logger = logging.getLogger("hydraflow.review_phase")


class ConvergenceJudgeMixin:
    """Convergence gate and post-verify lens judge of ``ReviewPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _APPROVE_GATE_LENSES: Any
    _advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan]
    _config: HydraFlowConfig
    _state: StateTracker

    if TYPE_CHECKING:

        async def _run_post_verify_for_surface(
            self,
            *,
            surface: str,
            diff: str,
            spec: str | None,
            executor_verdict_summary: str,
            executor_fix_diff: str | None = None,
            pre_flight_plan: ReviewPlan | None = None,
            attempt_number: int = 0,
            issue_number: int,
            log_pr_number: int | None = None,
            lens: Literal["correctness", "security", "spec"] | None = None,
            classification_paths: list[str] | None = None,
        ) -> PostVerifyResult | None: ...  # provided by _advisors

    def _lenses_for(self, n: int) -> list[Literal["correctness", "security", "spec"]]:
        """Return the first *n* PostVerify lens identifiers.

        Maps blast-radius pass count (1 / 2 / 3) to the ordered lens
        sequence used by the approve-path :class:`HybridGate` judge.
        """
        return self._APPROVE_GATE_LENSES[:n]

    def _approve_deterministic_check(
        self,
        code_scanning_alerts: list[Any] | None,
    ) -> DetResult:
        """Deterministic gate signal: block when open code-scanning alerts exist.

        Returns a :class:`~convergence_gate.DetResult` with ``ok=True`` when
        *code_scanning_alerts* is ``None`` or empty; ``ok=False`` with a
        human-readable failure message when at least one alert is present.
        """
        from convergence_gate import DetResult  # noqa: PLC0415

        if not code_scanning_alerts:
            return DetResult(ok=True)
        n = len(code_scanning_alerts)
        return DetResult(ok=False, failures=[f"open code-scanning alerts: {n}"])

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
    ) -> Callable[..., Any]:
        """Return an async ``judge(ctx, i) -> JudgeVerdict`` for the approve gate.

        The returned callable is the *judge* slot of a
        :class:`~convergence_gate.HybridGate`.  On each invocation it:

        1. Resolves the lens from ``_lenses_for(min_passes)[i]``.
        2. Calls :meth:`_run_post_verify_for_surface` with that lens.
        3. Maps ``PostVerifyResult.verdict == "APPROVE"`` →
           ``JudgeVerdict(approve=True)``; VETO → ``approve=False``.
        4. On any non-credit/non-bug exception: calls
           ``reraise_on_credit_or_bug`` first, then returns a degraded
           ``JudgeVerdict(approve=True, feedback="judge-degraded")``
           (fail-open, matching the ``HybridGate`` default).
        """
        from convergence_gate import JudgeVerdict  # noqa: PLC0415
        from exception_classify import reraise_on_credit_or_bug  # noqa: PLC0415
        from review_advisor import min_review_passes_for_blast_radius  # noqa: PLC0415

        async def _judge(ctx: Any, i: int) -> Any:
            n = min_review_passes_for_blast_radius(ctx.blast_radius)
            lens = self._lenses_for(n)[i]
            try:
                pv = await self._run_post_verify_for_surface(
                    surface=surface,
                    diff=diff,
                    spec=task.body or None,
                    executor_verdict_summary=(result.summary or result.verdict.value),
                    pre_flight_plan=self._advisor_pre_flight_plan.get(
                        (surface, pr.number)
                    ),
                    issue_number=task.id,
                    log_pr_number=pr.number,
                    lens=lens,
                )
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                return JudgeVerdict(approve=True, feedback="judge-degraded")
            if pv is None:
                # Advisor degraded (kill-switch off or runner crash) — fail open.
                return JudgeVerdict(approve=True, feedback="judge-degraded")
            # On VETO, record lens:disagreement for each blocking disagreement
            # so lap signatures reflect the actual disagreement content.
            sigs: list[str]
            if pv.verdict != "APPROVE" and pv.disagreements:
                sigs = sorted(
                    {f"{lens}:{d.advisor_assessment}" for d in pv.disagreements}
                )
            else:
                sigs = [lens]
            return JudgeVerdict(
                approve=pv.verdict == "APPROVE",
                feedback=pv.suggested_fix_direction,
                signatures=sigs,
            )

        return _judge

    async def _convergence_decision(
        self,
        *,
        issue_number: int,
        review_approved: bool,
        code_scanning_alerts: list[Any] | None = None,
        post_verify_judge: Callable[..., Any] | None = None,
        reject_review_result: Any | None = None,
    ) -> GateResult:
        """Run the convergence HybridGate for a review boundary.

        Reads blast radius from the ledger, evaluates the gate, records the
        decision (verdict + signatures + lap) back into the ledger, enforces
        the outer lap budget, and persists. Returns the (possibly lap-budget
        converted) :class:`GateResult`.

        Two boundaries route through here:

        * **reject** (``review_approved=False``): the deterministic check is
          RED (the verdict itself), so the gate loops back without judging —
          signatures derived from *reject_review_result.summary* (normalized)
          are recorded to enable lap-level oscillation detection.
        * **approve** (``review_approved=True``): the deterministic check is
          :meth:`_approve_deterministic_check` (RED when open code-scanning
          alerts exist → LOOP_BACK without judging; GREEN → the injected
          *post_verify_judge* lens passes run). All-lens APPROVE records
          ``last_verdict == "ADVANCE"``, which flips ``converged`` to True.
        """
        from convergence_gate import (  # noqa: PLC0415
            DetResult,
            GateContext,
            GateDecision,
            JudgeVerdict,
            build_review_gate,
            escalate,
        )

        radius = self._state.get_review_blast_radius(issue_number) or "low"
        ledger = self._state.ensure_convergence_ledger(
            issue_number,
            blast_radius=radius,  # type: ignore[arg-type]
        )
        attempts = ledger.get_attempts("review")
        max_attempts = self._config.max_review_fix_attempts

        if review_approved:
            approve_det = self._approve_deterministic_check(code_scanning_alerts)

            async def _det(_ctx: GateContext) -> DetResult:
                # Approve boundary: deterministic signal is the code-scanning
                # check. GREEN (no alerts) → the lens judge runs; RED → the
                # gate loops back without judging.
                return approve_det

            # The real lens judge is injected by the approve call site. Fall
            # back to a fail-open stub if a caller omits it.
            if post_verify_judge is not None:
                _judge = post_verify_judge
            else:
                logger.warning(
                    "convergence_decision: approve gate for issue #%d is using a "
                    "fail-open stub judge (post_verify_judge=None). No live caller "
                    "should reach this path; check call sites if seen in production.",
                    issue_number,
                )

                async def _judge(_ctx: GateContext, _i: int) -> JudgeVerdict:
                    return JudgeVerdict(approve=True)
        else:
            # Derive signatures from review result content for lap-signature
            # discrimination. ReviewResult has no separate comments list;
            # fall back to summary.
            _reject_sigs: list[str] = []
            if reject_review_result is not None:
                _summary = _normalize_text(reject_review_result.summary)
                if _summary:
                    _reject_sigs = [_summary]

            async def _det(_ctx: GateContext) -> DetResult:
                # Reject boundary: the review verdict itself is the
                # deterministic signal. review_approved is False, so the gate
                # never reaches the judge below. Signatures are passed so the
                # gate records them via loop_back for oscillation detection.
                return DetResult(ok=review_approved, signatures=_reject_sigs)

            async def _judge(_ctx: GateContext, _i: int) -> JudgeVerdict:
                # Unreached at the reject boundary (det is RED).
                return JudgeVerdict(approve=True)

        gate = build_review_gate(deterministic_check=_det, post_verify_judge=_judge)
        ctx = GateContext(
            issue_number=issue_number,
            stage="review",
            blast_radius=radius,  # type: ignore[arg-type]
            attempts=attempts,
            max_attempts=max_attempts,
        )
        result = await gate.evaluate(ctx)

        # Persist the decision into the ledger (single source of truth).
        if result.decision is GateDecision.LOOP_BACK:
            ledger.increment_attempts("review")
        ledger.record_gate_result(
            "review", result.decision.value, result.finding_signatures
        )
        ledger.mark_lap()

        # Outer lap budget: a LOOP_BACK that exhausts the lap cap becomes an
        # ESCALATE so the outer loop can never spin past max_convergence_laps.
        if (
            result.decision is GateDecision.LOOP_BACK
            and ledger.laps >= self._config.max_convergence_laps
        ):
            result = escalate(
                f"outer lap budget exhausted "
                f"({ledger.laps}/{self._config.max_convergence_laps})",
                result.finding_signatures,
            )
            ledger.record_gate_result(
                "review", result.decision.value, result.finding_signatures
            )

        ledger.recompute_converged(["review"])
        self._state.save_convergence_ledger(issue_number, ledger)
        return result

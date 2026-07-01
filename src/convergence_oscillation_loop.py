"""ConvergenceOscillationLoop — caretaker that detects and escalates cross-boundary oscillation.

Every ``convergence_oscillation_interval`` seconds the loop scans all
``ConvergenceLedger`` entries held in ``StateTracker``.  For each ledger that
is neither converged nor already escalated it calls
``detect_cross_boundary_oscillation`` (pure function on the ledger).  When the
detector fires, the loop files a ``hitl-escalation`` issue with the
``convergence-oscillation`` sub-label and marks the ledger so subsequent ticks
are skipped.

This loop makes NO LLM calls (``LONG_LLM_CYCLE = False``) and is therefore
subject to the tight ``loop_watchdog_default_seconds`` cycle bound.

Pattern refs:
  - ADR-0029 (caretaker pattern)
  - ADR-0049 (in-body kill-switch convention)
  - ``src/gate_activator_loop.py`` (loop_fitness shape)
  - ``src/triage_retry_loop.py`` (constructor shape + HITL escalation)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.convergence_oscillation_loop")


class ConvergenceOscillationLoop(BaseBackgroundLoop):
    """Caretaker loop: detect cross-boundary oscillation and escalate to HITL.

    Scans every ``ConvergenceLedger`` in ``StateTracker`` each tick.
    Ledgers that are converged or already escalated are skipped.  For the
    remainder, ``detect_cross_boundary_oscillation`` determines whether the
    issue is oscillating across triage/shape/plan boundaries; if so, a
    ``hitl-escalation`` issue is filed and the ledger is flagged so the
    issue is not re-escalated on future ticks.

    Follows ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch convention).
    """

    LONG_LLM_CYCLE = False

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="convergence_oscillation",
            config=config,
            deps=deps,
        )
        self._state = state
        self._pr = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.convergence_oscillation_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch gate (MANDATORY — literal call).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Static config gate (deploy-time disable). Defense-in-depth.
        if not self._config.convergence_oscillation_loop_enabled:
            return {"status": "config_disabled"}

        # Never file HITL issues during dry-run.
        if self._config.dry_run:
            return None

        escalated = 0
        scanned = 0

        for issue_number, ledger in self._state.iter_convergence_ledgers():
            scanned += 1

            if ledger.converged or ledger.oscillation_escalated:
                continue

            if ledger.detect_cross_boundary_oscillation(
                window=self._config.convergence_oscillation_window,
                min_loopback_stages=self._config.convergence_oscillation_min_loopback_stages,
            ):
                # Identify which boundary stages are currently LOOP_BACK so the
                # body gives operators a quick read on where the churn is.
                boundary_stages = {"triage", "shape", "plan"}
                loopback_stages = [
                    stage
                    for stage in sorted(boundary_stages)
                    if ledger.stage_state.get(stage) is not None
                    and ledger.stage_state[stage].last_verdict == "LOOP_BACK"
                ]
                loopback_str = (
                    ", ".join(f"`{s}`" for s in loopback_stages)
                    if loopback_stages
                    else "(temporal outer oscillation)"
                )

                title = f"HITL: convergence oscillation detected for #{issue_number}"
                body = (
                    f"`ConvergenceOscillationLoop` has detected cross-boundary "
                    f"oscillation on issue #{issue_number}.\n\n"
                    f"**Laps completed:** {ledger.laps}\n\n"
                    f"**Oscillating boundary stages:** {loopback_str}\n\n"
                    "The issue is cycling back across phase boundaries without "
                    "converging. Autonomous re-routing has not resolved the churn; "
                    "a human decision is required to unblock it.\n\n"
                    "Per ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch "
                    "convention), this escalation will not be repeated — the ledger "
                    "is flagged so subsequent ticks skip this issue."
                )
                labels = [
                    self._config.hitl_escalation_label[0],
                    "convergence-oscillation",
                ]

                try:
                    await self._pr.create_issue(title, body, labels)
                    self._state.mark_oscillation_escalated(issue_number)
                    escalated += 1
                except Exception as exc:  # noqa: BLE001
                    reraise_on_credit_or_bug(exc)
                    logger.warning(
                        "convergence_oscillation: failed to escalate issue #%d",
                        issue_number,
                        exc_info=True,
                    )

        return {"status": "ok", "scanned": scanned, "escalated": escalated}

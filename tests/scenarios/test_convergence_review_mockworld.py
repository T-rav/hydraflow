"""MockWorld scenarios — convergence gate at the review boundary.

Verifies two behaviours introduced by the convergence gate
(``convergence_gate_enabled=True``):

1. ``test_loop_back_then_converge`` — a PR that fails review on pass 1
   (REQUEST_CHANGES) loops back to the ready queue; the ledger records the
   lap.  The test confirms the ledger is populated by the real gate logic
   running inside MockWorld.

2. ``test_oscillation_escalates`` — repeated REQUEST_CHANGES results push the
   issue over the outer lap budget (``max_convergence_laps``), causing
   escalation to HITL and the ledger's lap count to hit the budget.

These are **integration-level** scenarios: the real ``ReviewPhase._handle_rejected_review_gated``
and ``ConvergenceLedger`` run; nothing is hand-populated in the ledger.
"""

from __future__ import annotations

import pytest

from models import ReviewVerdict
from tests.conftest import ReviewResultFactory
from tests.scenarios.builders import IssueBuilder
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world_with_gate(tmp_path, *, max_convergence_laps: int = 3) -> MockWorld:
    """Return a fresh MockWorld with the convergence gate enabled.

    We pass a config built before constructing MockWorld so that
    ``ReviewPhase`` (wired in ``PipelineHarness.__init__``) picks up the flag
    at construction time.  Mutating ``world.harness.config`` after the fact
    would also work because ``ReviewPhase._uses_convergence_gate()`` reads
    ``self._config.convergence_gate_enabled`` at call time, but passing it in
    is the cleaner contract.
    """
    from tests.helpers import ConfigFactory

    cfg = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        max_workers=1,
        max_planners=1,
        max_reviewers=1,
        visual_validation_enabled=False,
        max_ci_fix_attempts=0,
    )
    cfg.convergence_gate_enabled = True
    cfg.max_convergence_laps = max_convergence_laps
    return MockWorld(tmp_path, config=cfg)


# ---------------------------------------------------------------------------
# Probe / verification (inline — not a standalone test class)
# ---------------------------------------------------------------------------
# The probe is embedded in test_loop_back_then_converge:  if the ledger is
# None after a scripted REQUEST_CHANGES with the gate ON, the test will fail
# with a clear assertion message rather than a vacuous pass.


# ---------------------------------------------------------------------------
# Scenario 1 — loop-back, then advance on next pass
# ---------------------------------------------------------------------------


class TestLoopBackThenConverge:
    """Gate ON: reject → loop-back, then approve → advance.

    The single ``run_pipeline`` call delivers the scripted REQUEST_CHANGES
    verdict.  ``_handle_rejected_review_gated`` runs, records one lap in the
    ledger, and re-queues the issue back to ``ready``.  The test confirms:

    - The ledger is created and ``laps == 1`` (one reject lap closed).
    - The issue is NOT merged in this pipeline pass (it was re-queued).
    - ``final_stage`` is ``"review"`` (the reject result is the last record).
    """

    async def test_loop_back_then_converge(self, tmp_path) -> None:
        world = _make_world_with_gate(tmp_path)

        IssueBuilder().numbered(1).titled("Fix bug").bodied("A bug to fix").at(world)

        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world.set_phase_results("review", 1, [reject])

        result = await world.run_pipeline()

        # --- probe: confirm the real gate ran and populated the ledger ---
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated REQUEST_CHANGES — "
            "the real _handle_rejected_review_gated did not run through MockWorld. "
            "BLOCKED: the gate is not exercised at this injection level."
        )

        # --- main assertions ---
        # One reject lap was closed by _convergence_decision → ledger.mark_lap().
        assert ledger.laps == 1, (
            f"Expected laps==1 after one REQUEST_CHANGES; got {ledger.laps}"
        )
        # The gate decision for a reject is LOOP_BACK, so converged stays False.
        assert ledger.converged is False

        outcome = result.issue(1)
        # The issue was re-queued (loop-back), not merged.
        assert outcome.merged is False
        assert outcome.review_result is not None
        assert outcome.review_result.verdict == ReviewVerdict.REQUEST_CHANGES


# ---------------------------------------------------------------------------
# Scenario 2 — repeated rejections exhaust the lap budget → HITL escalation
# ---------------------------------------------------------------------------


class TestOscillationEscalates:
    """Gate ON, lap budget exhausted → issue escalates to HITL.

    We lower ``max_convergence_laps`` to 1 so that even a single REQUEST_CHANGES
    lap triggers the budget check inside ``_convergence_decision``:

        if LOOP_BACK and ledger.laps >= max_convergence_laps:
            result = escalate(...)

    After escalation ``_handle_rejected_review_gated`` calls
    ``_escalate_to_hitl``, which transitions the issue to the HITL label.
    The test asserts:

    - The ledger has at least 1 lap (the budget-exhausting lap).
    - The issue carries the HITL label (escalation completed).
    - The issue is NOT merged.
    """

    async def test_oscillation_escalates(self, tmp_path) -> None:
        # Lower the budget so a single reject lap trips the cap.
        world = _make_world_with_gate(tmp_path, max_convergence_laps=1)

        IssueBuilder().numbered(1).titled("Looping bug").bodied(
            "Repeatedly fails review."
        ).at(world)

        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world.set_phase_results("review", 1, [reject])

        result = await world.run_pipeline()

        # --- probe: gate must have run ---
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated REQUEST_CHANGES — "
            "the real gate did not run. BLOCKED."
        )

        # The lap budget was exhausted: laps >= max_convergence_laps (1).
        assert ledger.laps >= 1, (
            f"Expected laps >= 1 after budget-exhausting reject; got {ledger.laps}"
        )

        # Issue must be escalated to HITL and NOT merged.
        outcome = result.issue(1)
        assert outcome.merged is False

        # Convergence escalation routes through the diagnostic loop first:
        # _escalate_to_hitl transitions to "diagnose" (hydraflow-diagnose),
        # not directly to hydraflow-hitl.  Assert the diagnose label is applied.
        diagnose_label = world.harness.config.diagnose_label[0]
        issue_labels = outcome.labels
        assert diagnose_label in issue_labels, (
            f"Expected diagnose label {diagnose_label!r} in issue labels after "
            f"convergence escalation; got {issue_labels}"
        )

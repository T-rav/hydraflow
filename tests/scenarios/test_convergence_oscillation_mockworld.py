"""MockWorld scenario for ConvergenceOscillationLoop (ADR-0098 Phase 2d).

Approach A (catalog path): drives the loop through
``MockWorld.run_with_loops(["convergence_oscillation"])`` so the Task-3
registration is exercised end-to-end.  A real ``StateTracker`` is pre-seeded
with oscillating and non-oscillating ledgers and injected via the
``convergence_oscillation_state`` port (recognised by
``_build_convergence_oscillation`` in ``catalog/loop_registrations.py``).
The escalation issue is observed through ``world._github._issues``, which is
the FakeGitHub that the builder wires as ``pr_manager``.

Non-vacuity: the escalation is produced by the real loop running on a real
ledger; the test asserts the issue existed before the loop ran AND that a
second (non-oscillating) ledger was not escalated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Helpers (mirror the unit-test seeders in test_convergence_oscillation_loop.py)
# ---------------------------------------------------------------------------


def _seed_oscillating_ledger(state, issue_number: int) -> None:
    """Triage + plan both LOOP_BACK → oscillation threshold crossed."""
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.record_gate_result("triage", "LOOP_BACK", ["finding-a"])
    ledger.record_gate_result("plan", "LOOP_BACK", ["finding-b"])
    state.save_convergence_ledger(issue_number, ledger)


def _seed_non_oscillating_ledger(state, issue_number: int) -> None:
    """Only triage LOOP_BACK (below min_loopback_stages=2) → no oscillation."""
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.record_gate_result("triage", "LOOP_BACK", ["finding-a"])
    ledger.record_gate_result("plan", "ADVANCE", [])
    state.save_convergence_ledger(issue_number, ledger)


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


class TestConvergenceOscillationMockWorld:
    """Catalog-path integration scenarios for ConvergenceOscillationLoop."""

    def test_loop_is_registered_in_catalog(self) -> None:
        """Task-3 registration is present; catalog path is valid."""
        assert LoopCatalog.is_registered("convergence_oscillation"), (
            "'convergence_oscillation' not found in LoopCatalog — "
            "check loop_registrations.py Task 3 registration"
        )

    async def test_oscillating_ledger_creates_hitl_issue(self, tmp_path) -> None:
        """Oscillating ledger → loop creates one HITL escalation issue.

        Non-vacuity probes:
        * Asserts the ledger existed in state BEFORE the loop ran.
        * Asserts the escalation issue carries the HITL + convergence-oscillation labels.
        * Asserts the ledger's oscillation_escalated flag is True after the run.
        """
        from state import StateTracker  # noqa: PLC0415

        state = StateTracker(tmp_path / "state.json")
        _seed_oscillating_ledger(state, 101)

        # Probe: ledger was seeded correctly before the loop runs.
        pre_run = state.get_convergence_ledger(101)
        assert pre_run is not None, (
            "pre-seed probe: ledger 101 must exist before loop runs"
        )

        world = MockWorld(tmp_path)
        _seed_ports(world, convergence_oscillation_state=state)

        results = await world.run_with_loops(["convergence_oscillation"], cycles=1)

        stats = results["convergence_oscillation"]
        assert stats == {"status": "ok", "scanned": 1, "escalated": 1}, (
            f"unexpected stats: {stats}"
        )

        # Exactly one new issue must have been created by the loop.
        created = [
            issue
            for issue in world._github._issues.values()
            if "convergence-oscillation" in issue.labels
        ]
        assert len(created) == 1, (
            f"expected 1 HITL escalation issue; got {[i.number for i in created]}"
        )
        esc_issue = created[0]
        assert "convergence-oscillation" in esc_issue.labels
        # HITL escalation label must be present (exact value from config).
        hitl_label = "hydraflow-hitl-escalation"
        assert hitl_label in esc_issue.labels, (
            f"HITL label '{hitl_label}' missing; got labels={esc_issue.labels}"
        )

        # The flag must be persisted in the live state tracker.
        post_run = state.get_convergence_ledger(101)
        assert post_run is not None
        assert post_run.oscillation_escalated is True, (
            "oscillation_escalated must be True after escalation"
        )

    async def test_non_oscillating_ledger_is_not_escalated(self, tmp_path) -> None:
        """A ledger below the oscillation threshold must not be escalated.

        Also seeds an oscillating ledger to confirm discrimination: only the
        oscillating issue gets an escalation; the non-oscillating one does not.
        """
        from state import StateTracker  # noqa: PLC0415

        state = StateTracker(tmp_path / "state.json")
        _seed_oscillating_ledger(state, 200)
        _seed_non_oscillating_ledger(state, 201)

        world = MockWorld(tmp_path)
        _seed_ports(world, convergence_oscillation_state=state)

        results = await world.run_with_loops(["convergence_oscillation"], cycles=1)

        stats = results["convergence_oscillation"]
        # Two ledgers scanned; only the oscillating one escalated.
        assert stats["scanned"] == 2
        assert stats["escalated"] == 1

        oscillation_issues = [
            issue
            for issue in world._github._issues.values()
            if "convergence-oscillation" in issue.labels
        ]
        # Exactly one escalation, not two.
        assert len(oscillation_issues) == 1

        # The non-oscillating ledger must NOT be marked escalated.
        non_osc = state.get_convergence_ledger(201)
        assert non_osc is not None
        assert non_osc.oscillation_escalated is False, (
            "non-oscillating ledger must not be escalated"
        )

    async def test_dedup_second_cycle_does_not_re_escalate(self, tmp_path) -> None:
        """Two consecutive cycles escalate the same oscillating issue exactly once."""
        from state import StateTracker  # noqa: PLC0415

        state = StateTracker(tmp_path / "state.json")
        _seed_oscillating_ledger(state, 300)

        world = MockWorld(tmp_path)
        _seed_ports(world, convergence_oscillation_state=state)

        # First cycle — must escalate.
        results1 = await world.run_with_loops(["convergence_oscillation"], cycles=1)
        assert results1["convergence_oscillation"]["escalated"] == 1

        # Second cycle — same state; must skip the already-escalated ledger.
        results2 = await world.run_with_loops(["convergence_oscillation"], cycles=1)
        assert results2["convergence_oscillation"]["escalated"] == 0

        # Only one issue was ever created.
        oscillation_issues = [
            issue
            for issue in world._github._issues.values()
            if "convergence-oscillation" in issue.labels
        ]
        assert len(oscillation_issues) == 1, (
            "dedup: a second cycle must not create a duplicate escalation issue"
        )

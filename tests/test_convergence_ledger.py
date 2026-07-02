from __future__ import annotations

import pytest

from models import ConvergenceLedger, StageRecord, StateData
from tests.helpers import make_tracker


class TestConvergenceLedgerModel:
    def test_round_trip_serialization(self) -> None:
        ledger = ConvergenceLedger(issue_number=7, blast_radius="high")
        ledger.increment_attempts("review")
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        restored = ConvergenceLedger.model_validate_json(ledger.model_dump_json())
        assert restored == ledger
        assert restored.stage_state["review"].attempts == 1
        assert restored.stage_state["review"].last_verdict == "LOOP_BACK"

    def test_increment_attempts_is_per_stage(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        assert ledger.get_attempts("review") == 0
        assert ledger.increment_attempts("review") == 1
        assert ledger.increment_attempts("review") == 2
        assert ledger.get_attempts("plan") == 0

    def test_recompute_converged_requires_all_gated_advance_and_no_concerns(
        self,
    ) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("review", "ADVANCE", [])
        assert ledger.recompute_converged(["review"]) is True
        assert ledger.converged is True

    def test_not_converged_when_a_gate_did_not_advance(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        assert ledger.recompute_converged(["review"]) is False

    def test_detect_outer_oscillation_when_lap_signatures_repeat(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        ledger.mark_lap()
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        ledger.mark_lap()
        assert ledger.detect_outer_oscillation(window=2) is True

    def test_no_oscillation_when_signatures_change(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        ledger.mark_lap()
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-b"])
        ledger.mark_lap()
        assert ledger.detect_outer_oscillation(window=2) is False

    def test_stage_record_round_trips(self) -> None:
        sr = StageRecord(
            last_verdict="ADVANCE", attempts=2, last_finding_signatures=["x"]
        )
        assert StageRecord.model_validate_json(sr.model_dump_json()) == sr

    def test_record_gate_result_rejects_invalid_verdict(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        with pytest.raises(ValueError):
            ledger.record_gate_result("review", "BOGUS", [])

    def test_recompute_converged_false_when_no_gates(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        assert ledger.recompute_converged([]) is False

    def test_state_data_with_ledger_round_trips(self) -> None:
        ledger = ConvergenceLedger(issue_number=7, blast_radius="high")
        ledger.increment_attempts("review")
        data = StateData(convergence_ledgers={"7": ledger})
        restored = StateData.model_validate_json(data.model_dump_json())
        assert restored.convergence_ledgers["7"].blast_radius == "high"
        assert restored.convergence_ledgers["7"].get_attempts("review") == 1


class TestConvergenceLedgerPersistence:
    def test_ensure_creates_and_persists(self, tmp_path) -> None:
        tracker = make_tracker(tmp_path)
        ledger = tracker.ensure_convergence_ledger(7, blast_radius="medium")
        ledger.increment_attempts("review")
        tracker.save_convergence_ledger(7, ledger)

        reloaded = make_tracker(tmp_path)
        reloaded.load()
        got = reloaded.get_convergence_ledger(7)
        assert got is not None
        assert got.blast_radius == "medium"
        assert got.get_attempts("review") == 1

    def test_clear_removes_ledger(self, tmp_path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.save_convergence_ledger(7, tracker.ensure_convergence_ledger(7))
        tracker.clear_convergence_ledger(7)
        assert tracker.get_convergence_ledger(7) is None


class TestDetectCrossBoundaryOscillation:
    def test_temporal_oscillation_triggers_true(self) -> None:
        # Arrange: two identical lap signatures => outer oscillation detected
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("review", "LOOP_BACK", ["x"])
        ledger.mark_lap()
        ledger.record_gate_result("review", "LOOP_BACK", ["x"])
        ledger.mark_lap()
        # lap_signatures is [["x"], ["x"]]
        # Act + Assert
        assert ledger.detect_cross_boundary_oscillation(window=2) is True

    def test_snapshot_oscillation_triggers_true(self) -> None:
        # Arrange: two distinct boundary stages with LOOP_BACK (no laps needed)
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("triage", "LOOP_BACK", [])
        ledger.record_gate_result("plan", "LOOP_BACK", [])
        # No marks => laps=0 => outer oscillation False, but snapshot True
        # Act + Assert
        assert ledger.detect_cross_boundary_oscillation(min_loopback_stages=2) is True

    def test_converged_advancing_ledger_returns_false(self) -> None:
        # Arrange: all stages ADVANCE, no repeated signatures
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("triage", "ADVANCE", ["sig-a"])
        ledger.mark_lap()
        ledger.record_gate_result("triage", "ADVANCE", ["sig-b"])
        ledger.mark_lap()
        # Act + Assert
        assert ledger.detect_cross_boundary_oscillation() is False

    def test_only_one_boundary_loopback_returns_false(self) -> None:
        # Arrange: only one boundary stage at LOOP_BACK, no outer oscillation
        ledger = ConvergenceLedger(issue_number=7)
        ledger.record_gate_result("triage", "LOOP_BACK", [])
        ledger.record_gate_result("shape", "ADVANCE", [])
        # Act + Assert: min_loopback_stages=2 not met
        assert ledger.detect_cross_boundary_oscillation(min_loopback_stages=2) is False

    def test_oscillation_escalated_field_defaults_false(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        assert ledger.oscillation_escalated is False

    def test_oscillation_escalated_round_trips(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        ledger.oscillation_escalated = True
        restored = ConvergenceLedger.model_validate_json(ledger.model_dump_json())
        assert restored.oscillation_escalated is True


class TestIterConvergenceLedgers:
    def test_iter_returns_all_ledgers_as_int_tuples(self, tmp_path) -> None:
        # Arrange: create two ledgers for different issues
        tracker = make_tracker(tmp_path)
        tracker.ensure_convergence_ledger(3)
        tracker.ensure_convergence_ledger(17)
        result = tracker.iter_convergence_ledgers()
        # Assert: both issues present as (int, ConvergenceLedger)
        issue_nums = {n for n, _ in result}
        assert issue_nums == {3, 17}
        for n, ledger in result:
            assert isinstance(n, int)
            assert isinstance(ledger, ConvergenceLedger)

    def test_iter_returns_deep_copies(self, tmp_path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.ensure_convergence_ledger(5)
        result = tracker.iter_convergence_ledgers()
        _, ledger = result[0]
        # Mutating returned copy must not affect stored state
        ledger.oscillation_escalated = True
        stored = tracker.get_convergence_ledger(5)
        assert stored is not None
        assert stored.oscillation_escalated is False

    def test_mark_oscillation_escalated_sets_flag_and_persists(self, tmp_path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.ensure_convergence_ledger(7)
        tracker.mark_oscillation_escalated(7)
        # Assert: flag set in memory
        ledger = tracker.get_convergence_ledger(7)
        assert ledger is not None
        assert ledger.oscillation_escalated is True
        # Assert: persists across reload
        reloaded = make_tracker(tmp_path)
        reloaded.load()
        restored = reloaded.get_convergence_ledger(7)
        assert restored is not None
        assert restored.oscillation_escalated is True

    def test_mark_oscillation_escalated_creates_ledger_if_absent(
        self, tmp_path
    ) -> None:
        tracker = make_tracker(tmp_path)
        # Issue 99 has no ledger yet
        assert tracker.get_convergence_ledger(99) is None
        tracker.mark_oscillation_escalated(99)
        ledger = tracker.get_convergence_ledger(99)
        assert ledger is not None
        assert ledger.oscillation_escalated is True

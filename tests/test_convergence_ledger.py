from __future__ import annotations

import pytest

from models import ConvergenceLedger, StageRecord


class TestConvergenceLedgerModel:
    def test_round_trip_serialization(self) -> None:
        # Arrange
        ledger = ConvergenceLedger(issue_number=7, blast_radius="high")
        ledger.increment_attempts("review")
        ledger.record_gate_result("review", "LOOP_BACK", ["sig-a"])
        # Act
        restored = ConvergenceLedger.model_validate_json(ledger.model_dump_json())
        # Assert
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
        sr = StageRecord(last_verdict="ADVANCE", attempts=2, last_finding_signatures=["x"])
        assert StageRecord.model_validate_json(sr.model_dump_json()) == sr

    def test_record_gate_result_rejects_invalid_verdict(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        with pytest.raises(ValueError):
            ledger.record_gate_result("review", "BOGUS", [])

    def test_recompute_converged_false_when_no_gates(self) -> None:
        ledger = ConvergenceLedger(issue_number=7)
        assert ledger.recompute_converged([]) is False

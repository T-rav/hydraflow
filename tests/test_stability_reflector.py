"""Tests for stability reflector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confidence_calibration import CalibrationStore, DecisionOutcome
from dora_tracker import DORATracker
from events import EventBus
from release_decision import ReleaseAction
from stability_reflector import StabilityAssessment, StabilityReflector
from tests.helpers import ConfigFactory


def _make_reflector(
    tmp_path: Path,
    *,
    events: list | None = None,
    outcomes: list[DecisionOutcome] | None = None,
) -> StabilityReflector:
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
    )
    state = MagicMock()
    bus = EventBus()
    if events:
        bus._history = list(events)
    dora = DORATracker(state, bus)
    store = CalibrationStore(tmp_path / "outcomes.jsonl")
    if outcomes:
        for o in outcomes:
            store.record_outcome(o)
    return StabilityReflector(dora, store, config)


def _make_outcome(
    *,
    correct: bool | None = True,
    action: ReleaseAction = ReleaseAction.AUTO_MERGE,
) -> DecisionOutcome:
    return DecisionOutcome(
        issue_number=1,
        pr_number=1,
        action=action,
        confidence_score=0.85,
        confidence_rank="high",
        risk_score=0.1,
        risk_level="low",
        mode="observe",
        outcome_correct=correct,
    )


class TestStabilityReflector:
    def test_assess_returns_assessment(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        result = reflector.assess()
        assert isinstance(result, StabilityAssessment)
        assert result.dora_trend == "stable"

    def test_first_assessment_is_stable(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        result = reflector.assess()
        assert result.dora_trend == "stable"
        # No outcomes → 0% accuracy → conservative posture
        assert result.risk_posture == "conservative"

    def test_accuracy_from_outcomes(self, tmp_path: Path) -> None:
        outcomes = [
            _make_outcome(correct=True),
            _make_outcome(correct=True),
            _make_outcome(correct=False),
        ]
        reflector = _make_reflector(tmp_path, outcomes=outcomes)
        result = reflector.assess()
        assert result.confidence_accuracy == pytest.approx(2 / 3, abs=0.01)

    def test_no_outcomes_zero_accuracy(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        result = reflector.assess()
        assert result.confidence_accuracy == 0.0

    def test_weight_drift_zero_with_defaults(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        result = reflector.assess()
        assert result.calibration_drift == 0.0

    def test_conservative_posture_on_low_accuracy(self, tmp_path: Path) -> None:
        outcomes = [
            _make_outcome(correct=False),
            _make_outcome(correct=False),
            _make_outcome(correct=True),
        ]
        reflector = _make_reflector(tmp_path, outcomes=outcomes)
        result = reflector.assess()
        assert result.risk_posture == "conservative"

    def test_reasoning_populated(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        result = reflector.assess()
        assert len(result.reasoning) > 0
        assert any("DORA trend" in r for r in result.reasoning)

    def test_suggest_mode_observe_for_low_accuracy(self, tmp_path: Path) -> None:
        outcomes = [_make_outcome(correct=False)] * 5
        reflector = _make_reflector(tmp_path, outcomes=outcomes)
        result = reflector.assess()
        assert result.suggested_mode == "observe"

    def test_multiple_assessments_track_trend(self, tmp_path: Path) -> None:
        reflector = _make_reflector(tmp_path)
        # First assessment establishes baseline
        reflector.assess()
        # Second should compare to first
        result = reflector.assess()
        assert result.dora_trend in ("improving", "stable", "degrading")

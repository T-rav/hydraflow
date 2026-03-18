"""Tests for confidence scoring module."""

from __future__ import annotations

import pytest

from confidence import (
    ConfidenceScore,
    ConfidenceSignals,
    ConfidenceWeights,
    _clamp,
    _normalize_ci_clean,
    _normalize_complexity,
    _normalize_delta_fidelity,
    _normalize_escalation_free,
    _normalize_history,
    _normalize_plan_quality,
    _normalize_review_clean,
    _normalize_rework_penalty,
    _normalize_security_clean,
    _normalize_visual_clean,
    _rank_from_score,
    compute_confidence,
)
from models import ReviewVerdict

# --- Normalization functions ---


class TestNormalizeComplexity:
    def test_min_complexity_gives_max_confidence(self) -> None:
        assert _normalize_complexity(0) == 1.0

    def test_max_complexity_gives_min_confidence(self) -> None:
        assert _normalize_complexity(10) == 0.0

    def test_mid_complexity(self) -> None:
        assert _normalize_complexity(5) == pytest.approx(0.5)


class TestNormalizePlanQuality:
    def test_perfect_plan(self) -> None:
        assert _normalize_plan_quality(100, 0) == 1.0

    def test_zero_actionability(self) -> None:
        assert _normalize_plan_quality(0, 0) == 0.0

    def test_validation_errors_penalize(self) -> None:
        assert _normalize_plan_quality(80, 3) == pytest.approx(0.5)

    def test_penalty_capped_at_half(self) -> None:
        assert _normalize_plan_quality(100, 10) == pytest.approx(0.5)

    def test_penalty_does_not_go_below_zero(self) -> None:
        assert _normalize_plan_quality(20, 10) == 0.0


class TestNormalizeDeltaFidelity:
    def test_no_drift(self) -> None:
        assert _normalize_delta_fidelity(False) == 1.0

    def test_drift(self) -> None:
        assert _normalize_delta_fidelity(True) == 0.5


class TestNormalizeReviewClean:
    def test_approve_no_fixes(self) -> None:
        assert _normalize_review_clean(ReviewVerdict.APPROVE, False) == 1.0

    def test_approve_with_fixes(self) -> None:
        assert _normalize_review_clean(ReviewVerdict.APPROVE, True) == 0.7

    def test_request_changes(self) -> None:
        assert _normalize_review_clean(ReviewVerdict.REQUEST_CHANGES, False) == 0.3

    def test_comment(self) -> None:
        assert _normalize_review_clean(ReviewVerdict.COMMENT, False) == 0.0


class TestNormalizeCiClean:
    def test_passed_no_fixes(self) -> None:
        assert _normalize_ci_clean(True, 0) == 1.0

    def test_passed_with_fix_attempts(self) -> None:
        assert _normalize_ci_clean(True, 2) == pytest.approx(0.6)

    def test_failed(self) -> None:
        assert _normalize_ci_clean(False, 0) == 0.0

    def test_none(self) -> None:
        assert _normalize_ci_clean(None, 0) == 0.0

    def test_many_fix_attempts_clamped(self) -> None:
        assert _normalize_ci_clean(True, 10) == 0.0


class TestNormalizeVisualClean:
    def test_passed(self) -> None:
        assert _normalize_visual_clean(True) == 1.0

    def test_failed(self) -> None:
        assert _normalize_visual_clean(False) == 0.0

    def test_not_checked(self) -> None:
        assert _normalize_visual_clean(None) == 0.5


class TestNormalizeEscalationFree:
    def test_no_reasons(self) -> None:
        assert _normalize_escalation_free([]) == 1.0

    def test_one_reason(self) -> None:
        assert _normalize_escalation_free(["low confidence"]) == 0.75

    def test_four_reasons_is_zero(self) -> None:
        assert _normalize_escalation_free(["a", "b", "c", "d"]) == 0.0

    def test_many_reasons_clamped(self) -> None:
        assert _normalize_escalation_free(["a"] * 10) == 0.0


class TestNormalizeSecurityClean:
    def test_no_alerts(self) -> None:
        assert _normalize_security_clean(0) == 1.0

    def test_one_alert(self) -> None:
        assert _normalize_security_clean(1) == pytest.approx(0.8)

    def test_five_alerts_is_zero(self) -> None:
        assert _normalize_security_clean(5) == 0.0


class TestNormalizeHistory:
    def test_perfect_history(self) -> None:
        assert _normalize_history(1.0, 0.0) == 1.0

    def test_no_approvals(self) -> None:
        assert _normalize_history(0.0, 0.0) == 0.0

    def test_high_rework_penalizes(self) -> None:
        assert _normalize_history(0.9, 0.5) == pytest.approx(0.45)


class TestNormalizeReworkPenalty:
    def test_no_rework(self) -> None:
        assert _normalize_rework_penalty(0.0) == 1.0

    def test_full_rework(self) -> None:
        assert _normalize_rework_penalty(1.0) == 0.0


class TestRankFromScore:
    def test_high(self) -> None:
        assert _rank_from_score(0.80) == "high"
        assert _rank_from_score(0.95) == "high"

    def test_medium(self) -> None:
        assert _rank_from_score(0.60) == "medium"
        assert _rank_from_score(0.79) == "medium"

    def test_low(self) -> None:
        assert _rank_from_score(0.59) == "low"
        assert _rank_from_score(0.0) == "low"


class TestClamp:
    def test_within_range(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_below(self) -> None:
        assert _clamp(-0.1) == 0.0

    def test_above(self) -> None:
        assert _clamp(1.5) == 1.0


# --- compute_confidence ---


class TestComputeConfidence:
    def test_perfect_signals_yield_high(self) -> None:
        signals = ConfidenceSignals(
            complexity_score=0,
            plan_actionability=100,
            plan_validation_errors=0,
            delta_has_drift=False,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            ci_fix_attempts=0,
            visual_passed=True,
            fixes_made=False,
            escalation_reasons=[],
            code_scanning_alert_count=0,
            historical_approval_rate=1.0,
            historical_rework_rate=0.0,
        )
        result = compute_confidence(signals)
        assert result.rank == "high"
        assert result.score >= 0.95

    def test_worst_case_signals_yield_low(self) -> None:
        signals = ConfidenceSignals(
            complexity_score=10,
            plan_actionability=0,
            plan_validation_errors=10,
            delta_has_drift=True,
            review_verdict=ReviewVerdict.COMMENT,
            ci_passed=False,
            ci_fix_attempts=5,
            visual_passed=False,
            fixes_made=True,
            escalation_reasons=["a", "b", "c", "d"],
            code_scanning_alert_count=10,
            historical_approval_rate=0.0,
            historical_rework_rate=1.0,
        )
        result = compute_confidence(signals)
        assert result.rank == "low"
        assert result.score < 0.10

    def test_cold_start_defaults(self) -> None:
        """Default signals (cold start) should produce a defined result."""
        result = compute_confidence(ConfidenceSignals())
        assert isinstance(result, ConfidenceScore)
        assert 0.0 <= result.score <= 1.0

    def test_custom_weights(self) -> None:
        signals = ConfidenceSignals(
            complexity_score=0,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
        )
        weights = ConfidenceWeights(review_clean=0.40)
        result = compute_confidence(signals, weights)
        assert result.weights_used.review_clean == 0.40

    def test_all_components_present(self) -> None:
        result = compute_confidence(ConfidenceSignals())
        expected_keys = {
            "complexity",
            "plan_quality",
            "delta_fidelity",
            "review_clean",
            "ci_clean",
            "visual_clean",
            "escalation_free",
            "security_clean",
            "history",
            "rework_penalty",
        }
        assert set(result.components.keys()) == expected_keys

    def test_signals_summary_not_empty(self) -> None:
        result = compute_confidence(ConfidenceSignals())
        assert isinstance(result.signals_summary, str)
        assert len(result.signals_summary) > 0

    def test_ci_flaky_moderate_confidence(self) -> None:
        signals = ConfidenceSignals(
            complexity_score=3,
            plan_actionability=80,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            ci_fix_attempts=2,
            visual_passed=True,
            historical_approval_rate=0.8,
        )
        result = compute_confidence(signals)
        assert result.rank in ("medium", "high")
        # CI flakiness should lower the score somewhat
        perfect = ConfidenceSignals(
            complexity_score=3,
            plan_actionability=80,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            ci_fix_attempts=0,
            visual_passed=True,
            historical_approval_rate=0.8,
        )
        perfect_result = compute_confidence(perfect)
        assert result.score < perfect_result.score

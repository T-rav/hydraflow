"""Test scenario factories for the confidence scoring system.

Provides pre-built signal configurations for common test scenarios.
"""

from __future__ import annotations

from confidence import ConfidenceSignals
from models import ReviewVerdict
from risk_model import RiskDimensions


class ConfidenceSignalsFactory:
    """Generate synthetic ConfidenceSignals for test scenarios."""

    @staticmethod
    def perfect() -> ConfidenceSignals:
        """All signals optimal — should yield ~1.0 confidence."""
        return ConfidenceSignals(
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

    @staticmethod
    def worst_case() -> ConfidenceSignals:
        """All signals bad — should yield ~0.0 confidence."""
        return ConfidenceSignals(
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

    @staticmethod
    def cold_start() -> ConfidenceSignals:
        """No historical data, minimal signals — tests default behavior."""
        return ConfidenceSignals()

    @staticmethod
    def ci_flaky(fix_attempts: int = 2) -> ConfidenceSignals:
        """CI passed but required multiple fix attempts."""
        return ConfidenceSignals(
            complexity_score=3,
            plan_actionability=80,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            ci_fix_attempts=fix_attempts,
            visual_passed=True,
            historical_approval_rate=0.8,
        )

    @staticmethod
    def high_risk_approve() -> ConfidenceSignals:
        """High confidence but touching risky paths."""
        return ConfidenceSignals(
            complexity_score=2,
            plan_actionability=90,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            visual_passed=True,
            historical_approval_rate=0.9,
            escalation_reasons=["high_risk_files_touched"],
        )

    @staticmethod
    def visual_regression() -> ConfidenceSignals:
        """Visual validation failed, everything else fine."""
        return ConfidenceSignals(
            complexity_score=2,
            plan_actionability=90,
            review_verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            visual_passed=False,
            historical_approval_rate=0.9,
        )


class RiskDimensionsFactory:
    """Generate synthetic RiskDimensions for test scenarios."""

    @staticmethod
    def tests_only() -> RiskDimensions:
        return RiskDimensions(
            files_changed=["tests/test_foo.py", "tests/test_bar.py"],
            diff_line_count=200,
            touches_tests_only=True,
        )

    @staticmethod
    def infra_change() -> RiskDimensions:
        return RiskDimensions(
            files_changed=[".github/workflows/ci.yml", "Dockerfile"],
            diff_line_count=50,
            touches_config=True,
            high_risk_paths_touched=True,
        )

    @staticmethod
    def large_feature(lines: int = 1500) -> RiskDimensions:
        return RiskDimensions(
            files_changed=[f"src/module_{i}.py" for i in range(15)],
            diff_line_count=lines,
            issue_type="feature",
        )

    @staticmethod
    def epic_child() -> RiskDimensions:
        return RiskDimensions(
            files_changed=["src/feature.py"],
            diff_line_count=100,
            is_epic_child=True,
            issue_type="feature",
        )

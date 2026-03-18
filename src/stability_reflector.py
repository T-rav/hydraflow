"""Stability reflector — runtime stability assessment engine.

Periodically assesses system health by combining DORA metrics, confidence
accuracy, calibration drift, and active failure patterns to recommend
risk posture and threshold adjustments.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from confidence import ConfidenceWeights
from confidence_calibration import CalibrationStore
from dora_tracker import DORASnapshot, DORATracker

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.stability_reflector")


class StabilityAssessment(BaseModel):
    """Point-in-time assessment of system stability."""

    dora: DORASnapshot
    dora_trend: Literal["improving", "stable", "degrading"] = "stable"
    confidence_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    calibration_drift: float = Field(default=0.0, ge=0.0)
    suggested_mode: Literal["observe", "advisory", "enforce"] = "observe"
    risk_posture: Literal["aggressive", "balanced", "conservative"] = "balanced"
    reasoning: list[str] = Field(default_factory=list)


class StabilityReflector:
    """Reflects on runtime data to assess and adapt system behavior."""

    def __init__(
        self,
        dora: DORATracker,
        calibration: CalibrationStore,
        config: HydraFlowConfig,
    ) -> None:
        self._dora = dora
        self._calibration = calibration
        self._config = config
        self._previous_snapshots: list[DORASnapshot] = []

    def assess(self) -> StabilityAssessment:
        """Compute current stability assessment from all runtime signals."""
        current = self._dora.snapshot()
        trend = self._compute_dora_trend(current)
        accuracy = self._compute_decision_accuracy()
        drift = self._compute_weight_drift()
        posture = self._suggest_posture(trend, accuracy)
        mode = self._suggest_mode(accuracy, trend)
        reasoning = self._build_reasoning(trend, accuracy, drift, posture)

        self._previous_snapshots.append(current)
        if len(self._previous_snapshots) > 100:
            self._previous_snapshots = self._previous_snapshots[-100:]

        return StabilityAssessment(
            dora=current,
            dora_trend=trend,
            confidence_accuracy=accuracy,
            calibration_drift=drift,
            suggested_mode=mode,
            risk_posture=posture,
            reasoning=reasoning,
        )

    def _compute_dora_trend(
        self,
        current: DORASnapshot,
    ) -> Literal["improving", "stable", "degrading"]:
        """Compare current snapshot to previous to detect trend."""
        if not self._previous_snapshots:
            return "stable"

        prev = self._previous_snapshots[-1]

        improvements = 0
        degradations = 0

        if current.change_failure_rate < prev.change_failure_rate - 0.02:
            improvements += 1
        elif current.change_failure_rate > prev.change_failure_rate + 0.02:
            degradations += 1

        if current.rework_rate < prev.rework_rate - 0.02:
            improvements += 1
        elif current.rework_rate > prev.rework_rate + 0.02:
            degradations += 1

        if current.deployment_frequency > prev.deployment_frequency + 0.1:
            improvements += 1
        elif current.deployment_frequency < prev.deployment_frequency - 0.1:
            degradations += 1

        if improvements > degradations:
            return "improving"
        if degradations > improvements:
            return "degrading"
        return "stable"

    def _compute_decision_accuracy(self) -> float:
        """What % of our release decisions were correct?"""
        judged = self._calibration.outcomes_with_judgement()
        if not judged:
            return 0.0
        correct = sum(1 for o in judged if o.outcome_correct is True)
        return correct / len(judged)

    def _compute_weight_drift(self) -> float:
        """How far have calibrated weights drifted from defaults?"""
        defaults = ConfidenceWeights()
        current = ConfidenceWeights(
            complexity=self._config.confidence_weight_complexity,
            plan_quality=self._config.confidence_weight_plan_quality,
            delta_fidelity=self._config.confidence_weight_delta_fidelity,
            review_clean=self._config.confidence_weight_review_clean,
            ci_clean=self._config.confidence_weight_ci_clean,
            visual_clean=self._config.confidence_weight_visual_clean,
            escalation_free=self._config.confidence_weight_escalation_free,
            security_clean=self._config.confidence_weight_security_clean,
            history=self._config.confidence_weight_history,
            rework_penalty=self._config.confidence_weight_rework_penalty,
        )
        default_data = defaults.model_dump()
        current_data = current.model_dump()
        total_drift = sum(abs(current_data[k] - default_data[k]) for k in default_data)
        return round(total_drift, 4)

    def _suggest_posture(
        self,
        trend: str,
        accuracy: float,
    ) -> Literal["aggressive", "balanced", "conservative"]:
        """Recommend risk posture based on combined signals."""
        if trend == "degrading" or accuracy < 0.5:
            return "conservative"
        if trend == "improving" and accuracy > 0.8:
            return "aggressive"
        return "balanced"

    def _suggest_mode(
        self,
        accuracy: float,
        trend: str,
    ) -> Literal["observe", "advisory", "enforce"]:
        """Suggest the appropriate mode based on system maturity."""
        if accuracy >= 0.8 and trend in ("stable", "improving"):
            return "enforce"
        if accuracy >= 0.6:
            return "advisory"
        return "observe"

    def _build_reasoning(
        self,
        trend: str,
        accuracy: float,
        drift: float,
        posture: str,
    ) -> list[str]:
        """Build human-readable reasoning for the assessment."""
        reasons: list[str] = []
        reasons.append(f"DORA trend: {trend}")
        reasons.append(f"Decision accuracy: {accuracy:.1%}")
        if drift > 0.1:
            reasons.append(
                f"Weight drift {drift:.3f} from defaults — review calibration"
            )
        reasons.append(f"Recommended posture: {posture}")
        return reasons

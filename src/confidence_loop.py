"""Background calibration loop for the confidence system.

Extends BaseBackgroundLoop. Periodically recalibrates confidence weights
from decision outcomes and publishes DORA health snapshots.
"""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from confidence import ConfidenceWeights
from confidence_calibration import CalibrationStore, calibrate_weights
from config import HydraFlowConfig
from dora_tracker import DORATracker
from events import EventType, HydraFlowEvent
from release_decision import ReleasePolicy
from stability_reflector import StabilityReflector

logger = logging.getLogger("hydraflow.confidence_loop")


class ConfidenceCalibrationLoop(BaseBackgroundLoop):
    """Background loop that calibrates confidence weights from outcomes."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        calibration_store: CalibrationStore,
        dora_tracker: DORATracker,
        reflector: StabilityReflector | None = None,
    ) -> None:
        super().__init__(
            worker_name="confidence_calibration",
            config=config,
            deps=deps,
        )
        self._calibration_store = calibration_store
        self._dora = dora_tracker
        self._reflector = reflector

    def _get_default_interval(self) -> int:
        return self._config.confidence_calibration_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.confidence_calibration_enabled:
            return {"skipped": True, "reason": "calibration disabled"}

        # 1. Publish DORA health snapshot
        dora_snap = self._dora.snapshot()
        policy = ReleasePolicy(
            max_rework_rate=self._config.dora_max_rework_rate,
            max_change_failure_rate=self._config.dora_max_change_failure_rate,
        )
        healthy = self._dora.is_healthy(policy)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.DORA_HEALTH,
                data={
                    "deployment_frequency": dora_snap.deployment_frequency,
                    "lead_time_seconds": dora_snap.lead_time_seconds,
                    "change_failure_rate": dora_snap.change_failure_rate,
                    "recovery_time_seconds": dora_snap.recovery_time_seconds,
                    "rework_rate": dora_snap.rework_rate,
                    "healthy": healthy,
                },
            )
        )

        if not healthy:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_HEALTH_ALERT,
                    data={
                        "source": "dora_tracker",
                        "message": (
                            f"DORA health degraded: rework_rate={dora_snap.rework_rate:.3f}, "
                            f"change_failure_rate={dora_snap.change_failure_rate:.3f}"
                        ),
                    },
                )
            )

        # 2. Calibrate weights if enough samples
        outcomes = self._calibration_store.load_outcomes()
        current_weights = ConfidenceWeights(
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

        new_weights, cal_stats = calibrate_weights(
            current_weights,
            outcomes,
            min_samples=self._config.confidence_calibration_min_samples,
            max_adjustment=self._config.confidence_calibration_max_adjustment,
        )

        if cal_stats.get("adjusted"):
            logger.info(
                "Confidence weights calibrated: direction=%s, accuracy=%.2f",
                cal_stats.get("adjustment_direction"),
                cal_stats.get("accuracy", 0.0),
            )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CONFIDENCE_CALIBRATION,
                data={
                    "weights_adjusted": cal_stats.get("adjusted", False),
                    "accuracy": cal_stats.get("accuracy"),
                    "direction": cal_stats.get("adjustment_direction"),
                    "total_outcomes": cal_stats.get("total_outcomes", 0),
                    "judged_outcomes": cal_stats.get("judged_outcomes", 0),
                },
            )
        )

        # 3. Stability reflection (if enabled)
        stability_result: dict[str, Any] = {}
        if self._reflector is not None and self._config.stability_reflection_enabled:
            assessment = self._reflector.assess()
            stability_result = {
                "risk_posture": assessment.risk_posture,
                "dora_trend": assessment.dora_trend,
                "accuracy": assessment.confidence_accuracy,
            }
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.STABILITY_ASSESSMENT,
                    data=assessment.model_dump(),
                )
            )

        return {
            "dora_healthy": healthy,
            "calibration": cal_stats,
            **stability_result,
        }

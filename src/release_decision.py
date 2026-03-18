"""Release decision engine — combines confidence, risk, and DORA health.

Pure-function module. Maps (confidence, risk, DORA health) to a release action.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from confidence import ConfidenceScore
from risk_model import RiskScore


class ReleaseAction(StrEnum):
    """Possible actions from the decision engine."""

    AUTO_MERGE = "auto_merge"
    STAGE = "stage"
    HOLD_FOR_REVIEW = "hold_for_review"
    ESCALATE_HITL = "escalate_hitl"
    REJECT = "reject"


class ReleasePolicy(BaseModel):
    """Configurable thresholds from HydraFlowConfig."""

    auto_merge_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    stage_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    hold_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    reject_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    max_rework_rate: float = Field(default=0.15, ge=0.0, le=1.0)
    max_change_failure_rate: float = Field(default=0.20, ge=0.0, le=1.0)


ReleaseMode = Literal["off", "observe", "advisory", "enforce"]


class ReleaseDecision(BaseModel):
    """Outcome of the release decision engine."""

    action: ReleaseAction
    confidence: ConfidenceScore
    risk: RiskScore
    reasons: list[str]
    mode: ReleaseMode
    dora_health: dict[str, float] = Field(default_factory=dict)


def _is_dora_healthy(
    dora_health: dict[str, float],
    policy: ReleasePolicy,
) -> bool:
    rework = dora_health.get("rework_rate", 0.0)
    cfr = dora_health.get("change_failure_rate", 0.0)
    return rework <= policy.max_rework_rate and cfr <= policy.max_change_failure_rate


def _base_action(
    confidence: ConfidenceScore,
    risk: RiskScore,
    policy: ReleasePolicy,
) -> tuple[ReleaseAction, list[str]]:
    """Determine the base action from confidence × risk matrix."""
    c = confidence.score
    reasons: list[str] = []

    # Reject: very low confidence + high risk
    if c < policy.reject_confidence and risk.level in ("high", "critical"):
        reasons.append(
            f"confidence {c:.2f} < {policy.reject_confidence} with {risk.level} risk"
        )
        return ReleaseAction.REJECT, reasons

    # Escalate: low confidence
    if c < policy.hold_confidence:
        reasons.append(f"confidence {c:.2f} < {policy.hold_confidence}")
        return ReleaseAction.ESCALATE_HITL, reasons

    # Hold: medium confidence with medium+ risk
    if c < policy.stage_confidence:
        reasons.append(f"confidence {c:.2f} < {policy.stage_confidence}")
        return ReleaseAction.HOLD_FOR_REVIEW, reasons

    # Stage: good confidence but not great, or high risk
    if c < policy.auto_merge_confidence:
        reasons.append(f"confidence {c:.2f} between stage and auto-merge thresholds")
        return ReleaseAction.STAGE, reasons

    # High confidence + high risk → stage for safety
    if risk.level in ("high", "critical"):
        reasons.append(
            f"confidence {c:.2f} is high but risk is {risk.level} — routing to stage"
        )
        return ReleaseAction.STAGE, reasons

    # High confidence + low/medium risk → auto-merge
    reasons.append(
        f"confidence {c:.2f} >= {policy.auto_merge_confidence} with {risk.level} risk"
    )
    return ReleaseAction.AUTO_MERGE, reasons


_ACTION_ORDER = [
    ReleaseAction.AUTO_MERGE,
    ReleaseAction.STAGE,
    ReleaseAction.HOLD_FOR_REVIEW,
    ReleaseAction.ESCALATE_HITL,
    ReleaseAction.REJECT,
]


def _downgrade(action: ReleaseAction) -> ReleaseAction:
    idx = _ACTION_ORDER.index(action)
    if idx < len(_ACTION_ORDER) - 1:
        return _ACTION_ORDER[idx + 1]
    return action


def decide_release(
    confidence: ConfidenceScore,
    risk: RiskScore,
    policy: ReleasePolicy | None = None,
    dora_health: dict[str, float] | None = None,
    mode: ReleaseMode = "off",
) -> ReleaseDecision:
    """Compute a release decision from confidence, risk, and DORA health.

    When *mode* is ``"off"``, the decision is still computed (for logging)
    but should not be enforced by callers.
    """
    pol = policy or ReleasePolicy()
    health = dora_health or {}

    action, reasons = _base_action(confidence, risk, pol)

    # DORA health gate: degraded system → downgrade one level
    if health and not _is_dora_healthy(health, pol):
        original = action
        action = _downgrade(action)
        reasons.append(
            f"DORA health degraded — downgraded {original.value} → {action.value}"
        )

    return ReleaseDecision(
        action=action,
        confidence=confidence,
        risk=risk,
        reasons=reasons,
        mode=mode,
        dora_health=health,
    )

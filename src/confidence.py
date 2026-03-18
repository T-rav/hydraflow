"""Confidence model — aggregates signals into a weighted 0.0–1.0 score.

Pure-function module. Collects Tier 1–3 signals from existing phase outputs
and computes a single confidence score used by the release decision engine.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models import ReviewVerdict


class ConfidenceSignals(BaseModel):
    """Raw inputs aggregated from existing phase outputs."""

    # Tier 1: Pre-merge
    complexity_score: int = Field(default=5, ge=0, le=10)
    plan_actionability: int = Field(default=50, ge=0, le=100)
    plan_validation_errors: int = Field(default=0, ge=0)
    delta_has_drift: bool = False
    review_verdict: ReviewVerdict = ReviewVerdict.COMMENT
    ci_passed: bool | None = None
    ci_fix_attempts: int = Field(default=0, ge=0)
    visual_passed: bool | None = None
    fixes_made: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)
    code_scanning_alert_count: int = Field(default=0, ge=0)

    # Tier 3: Historical
    historical_approval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    historical_rework_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    recent_failure_pattern_count: int = Field(default=0, ge=0)


class ConfidenceWeights(BaseModel):
    """Per-dimension weights. Each clamped to [0.05, 0.40]."""

    complexity: float = Field(default=0.10, ge=0.05, le=0.40)
    plan_quality: float = Field(default=0.15, ge=0.05, le=0.40)
    delta_fidelity: float = Field(default=0.05, ge=0.05, le=0.40)
    review_clean: float = Field(default=0.20, ge=0.05, le=0.40)
    ci_clean: float = Field(default=0.15, ge=0.05, le=0.40)
    visual_clean: float = Field(default=0.10, ge=0.05, le=0.40)
    escalation_free: float = Field(default=0.05, ge=0.05, le=0.40)
    security_clean: float = Field(default=0.05, ge=0.05, le=0.40)
    history: float = Field(default=0.10, ge=0.05, le=0.40)
    rework_penalty: float = Field(default=0.05, ge=0.05, le=0.40)


ConfidenceRank = Literal["high", "medium", "low"]


class ConfidenceScore(BaseModel):
    """Computed confidence score with breakdown."""

    score: float = Field(ge=0.0, le=1.0)
    rank: ConfidenceRank
    components: dict[str, float]
    weights_used: ConfidenceWeights
    signals_summary: str


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _normalize_complexity(score: int) -> float:
    return 1.0 - (score / 10.0)


def _normalize_plan_quality(actionability: int, validation_errors: int) -> float:
    base = actionability / 100.0
    penalty = min(validation_errors * 0.1, 0.5)
    return _clamp(base - penalty)


def _normalize_delta_fidelity(has_drift: bool) -> float:
    return 0.5 if has_drift else 1.0


def _normalize_review_clean(verdict: ReviewVerdict, fixes_made: bool) -> float:
    if verdict == ReviewVerdict.APPROVE:
        return 0.7 if fixes_made else 1.0
    if verdict == ReviewVerdict.REQUEST_CHANGES:
        return 0.3
    return 0.0  # COMMENT or unknown


def _normalize_ci_clean(ci_passed: bool | None, fix_attempts: int) -> float:
    if ci_passed is None:
        return 0.0
    if not ci_passed:
        return 0.0
    return _clamp(1.0 - 0.2 * fix_attempts)


def _normalize_visual_clean(visual_passed: bool | None) -> float:
    if visual_passed is None:
        return 0.5
    return 1.0 if visual_passed else 0.0


def _normalize_escalation_free(reasons: list[str]) -> float:
    return _clamp(1.0 - 0.25 * len(reasons))


def _normalize_security_clean(alert_count: int) -> float:
    return _clamp(1.0 - 0.2 * alert_count)


def _normalize_history(approval_rate: float, rework_rate: float) -> float:
    return _clamp(approval_rate * (1.0 - rework_rate))


def _normalize_rework_penalty(rework_rate: float) -> float:
    return _clamp(1.0 - rework_rate)


def _rank_from_score(score: float) -> ConfidenceRank:
    if score >= 0.80:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def _build_summary(components: dict[str, float], rank: ConfidenceRank) -> str:
    parts: list[str] = []
    for name, value in sorted(components.items(), key=lambda kv: kv[1]):
        if value < 0.5:
            parts.append(f"⚠ {name}={value:.2f}")
    if not parts:
        return f"All signals healthy (rank={rank})"
    return f"Weak signals: {', '.join(parts)} (rank={rank})"


def compute_confidence(
    signals: ConfidenceSignals,
    weights: ConfidenceWeights | None = None,
) -> ConfidenceScore:
    """Compute a weighted confidence score from raw signals.

    Returns a :class:`ConfidenceScore` with a 0.0–1.0 score, a rank
    (high/medium/low), per-dimension breakdown, and a human-readable summary.
    """
    w = weights or ConfidenceWeights()

    components: dict[str, float] = {
        "complexity": _normalize_complexity(signals.complexity_score),
        "plan_quality": _normalize_plan_quality(
            signals.plan_actionability, signals.plan_validation_errors
        ),
        "delta_fidelity": _normalize_delta_fidelity(signals.delta_has_drift),
        "review_clean": _normalize_review_clean(
            signals.review_verdict, signals.fixes_made
        ),
        "ci_clean": _normalize_ci_clean(signals.ci_passed, signals.ci_fix_attempts),
        "visual_clean": _normalize_visual_clean(signals.visual_passed),
        "escalation_free": _normalize_escalation_free(signals.escalation_reasons),
        "security_clean": _normalize_security_clean(signals.code_scanning_alert_count),
        "history": _normalize_history(
            signals.historical_approval_rate, signals.historical_rework_rate
        ),
        "rework_penalty": _normalize_rework_penalty(signals.historical_rework_rate),
    }

    weight_map: dict[str, float] = {
        "complexity": w.complexity,
        "plan_quality": w.plan_quality,
        "delta_fidelity": w.delta_fidelity,
        "review_clean": w.review_clean,
        "ci_clean": w.ci_clean,
        "visual_clean": w.visual_clean,
        "escalation_free": w.escalation_free,
        "security_clean": w.security_clean,
        "history": w.history,
        "rework_penalty": w.rework_penalty,
    }

    total_weight = sum(weight_map.values())
    if total_weight == 0:
        total_weight = 1.0

    score = sum(components[k] * weight_map[k] for k in components) / total_weight

    score = _clamp(score)
    rank = _rank_from_score(score)
    summary = _build_summary(components, rank)

    return ConfidenceScore(
        score=score,
        rank=rank,
        components=components,
        weights_used=w,
        signals_summary=summary,
    )

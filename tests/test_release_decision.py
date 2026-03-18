"""Tests for release decision engine."""

from __future__ import annotations

from confidence import ConfidenceScore, ConfidenceWeights
from release_decision import (
    ReleaseAction,
    ReleaseDecision,
    ReleasePolicy,
    _downgrade,
    _is_dora_healthy,
    decide_release,
)
from risk_model import RiskScore


def _make_confidence(score: float, rank: str = "high") -> ConfidenceScore:
    return ConfidenceScore(
        score=score,
        rank=rank,
        components={},
        weights_used=ConfidenceWeights(),
        signals_summary=f"test score={score}",
    )


def _make_risk(
    score: float = 0.1,
    level: str = "low",
    blast_radius: str = "isolated",
) -> RiskScore:
    return RiskScore(
        score=score,
        level=level,
        factors=[],
        blast_radius=blast_radius,
    )


class TestIsDORAHealthy:
    def test_healthy(self) -> None:
        policy = ReleasePolicy()
        health = {"rework_rate": 0.05, "change_failure_rate": 0.10}
        assert _is_dora_healthy(health, policy) is True

    def test_rework_exceeds(self) -> None:
        policy = ReleasePolicy(max_rework_rate=0.10)
        health = {"rework_rate": 0.20, "change_failure_rate": 0.05}
        assert _is_dora_healthy(health, policy) is False

    def test_cfr_exceeds(self) -> None:
        policy = ReleasePolicy(max_change_failure_rate=0.10)
        health = {"rework_rate": 0.05, "change_failure_rate": 0.15}
        assert _is_dora_healthy(health, policy) is False

    def test_empty_health_is_healthy(self) -> None:
        assert _is_dora_healthy({}, ReleasePolicy()) is True


class TestDowngrade:
    def test_auto_merge_to_stage(self) -> None:
        assert _downgrade(ReleaseAction.AUTO_MERGE) == ReleaseAction.STAGE

    def test_stage_to_hold(self) -> None:
        assert _downgrade(ReleaseAction.STAGE) == ReleaseAction.HOLD_FOR_REVIEW

    def test_reject_stays_reject(self) -> None:
        assert _downgrade(ReleaseAction.REJECT) == ReleaseAction.REJECT


class TestDecideRelease:
    def test_high_confidence_low_risk_auto_merges(self) -> None:
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.AUTO_MERGE
        assert isinstance(result, ReleaseDecision)

    def test_high_confidence_high_risk_stages(self) -> None:
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.6, "high")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.STAGE

    def test_medium_confidence_stages(self) -> None:
        conf = _make_confidence(0.70, "medium")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.STAGE

    def test_low_confidence_holds(self) -> None:
        conf = _make_confidence(0.55, "low")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.HOLD_FOR_REVIEW

    def test_very_low_confidence_escalates(self) -> None:
        conf = _make_confidence(0.40, "low")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.ESCALATE_HITL

    def test_very_low_confidence_high_risk_rejects(self) -> None:
        conf = _make_confidence(0.20, "low")
        risk = _make_risk(0.8, "critical")
        result = decide_release(conf, risk)
        assert result.action == ReleaseAction.REJECT

    def test_degraded_dora_downgrades(self) -> None:
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.1, "low")
        health = {"rework_rate": 0.30, "change_failure_rate": 0.05}
        result = decide_release(conf, risk, dora_health=health)
        # Would be AUTO_MERGE but DORA degraded → downgraded to STAGE
        assert result.action == ReleaseAction.STAGE
        assert any("degraded" in r.lower() for r in result.reasons)

    def test_mode_propagated(self) -> None:
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk, mode="observe")
        assert result.mode == "observe"

    def test_custom_policy(self) -> None:
        policy = ReleasePolicy(auto_merge_confidence=0.95)
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk, policy=policy)
        # 0.90 < 0.95 threshold → STAGE instead of AUTO_MERGE
        assert result.action == ReleaseAction.STAGE

    def test_reasons_always_populated(self) -> None:
        conf = _make_confidence(0.50, "low")
        risk = _make_risk(0.1, "low")
        result = decide_release(conf, risk)
        assert len(result.reasons) > 0

    def test_dora_health_stored(self) -> None:
        conf = _make_confidence(0.90, "high")
        risk = _make_risk(0.1, "low")
        health = {"rework_rate": 0.05}
        result = decide_release(conf, risk, dora_health=health)
        assert result.dora_health == health

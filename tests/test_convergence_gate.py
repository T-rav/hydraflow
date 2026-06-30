"""Unit tests for convergence_gate module."""
from __future__ import annotations

from convergence_gate import GateDecision, advance, escalate, loop_back


class TestGateResultFactories:
    def test_advance_carries_signatures(self) -> None:
        r = advance(["s1"])
        assert r.decision is GateDecision.ADVANCE
        assert r.finding_signatures == ["s1"]

    def test_loop_back_carries_target_and_feedback(self) -> None:
        r = loop_back("ready", "fix the thing", ["s1"])
        assert r.decision is GateDecision.LOOP_BACK
        assert r.target_stage == "ready"
        assert r.feedback == "fix the thing"

    def test_escalate_carries_reason(self) -> None:
        r = escalate("cap exceeded")
        assert r.decision is GateDecision.ESCALATE
        assert r.reason == "cap exceeded"

"""Unit tests for convergence_gate module."""
from __future__ import annotations

import pytest

from convergence_gate import (
    DetResult,
    GateContext,
    GateDecision,
    HybridGate,
    JudgeVerdict,
    advance,
    escalate,
    loop_back,
)


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


def _ctx(blast="low", attempts=0, max_attempts=3) -> GateContext:
    return GateContext(
        issue_number=7,
        stage="review",
        blast_radius=blast,
        attempts=attempts,
        max_attempts=max_attempts,
    )


class TestHybridGate:
    @pytest.mark.asyncio
    async def test_red_deterministic_loops_back_and_skips_judge(self) -> None:
        judge_calls = 0

        async def det(_c):
            return DetResult(ok=False, failures=["ci red"], signatures=["d1"])

        async def judge(_c, _i):
            nonlocal judge_calls
            judge_calls += 1
            return JudgeVerdict(approve=True)

        gate = HybridGate("review", deterministic=det, judge=judge)
        r = await gate.evaluate(_ctx())
        assert r.decision is GateDecision.LOOP_BACK
        assert judge_calls == 0
        assert "ci red" in (r.feedback or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blast,expected", [("low", 1), ("medium", 2), ("high", 3)])
    async def test_runs_n_judge_passes_by_blast_radius(self, blast, expected) -> None:
        calls = 0

        async def det(_c):
            return DetResult(ok=True)

        async def judge(_c, _i):
            nonlocal calls
            calls += 1
            return JudgeVerdict(approve=True)

        gate = HybridGate("review", deterministic=det, judge=judge)
        r = await gate.evaluate(_ctx(blast=blast))
        assert r.decision is GateDecision.ADVANCE
        assert calls == expected

    @pytest.mark.asyncio
    async def test_judge_veto_under_budget_loops_back(self) -> None:
        async def det(_c):
            return DetResult(ok=True)

        async def judge(_c, _i):
            return JudgeVerdict(approve=False, feedback="weak test")

        gate = HybridGate("review", deterministic=det, judge=judge)
        r = await gate.evaluate(_ctx(attempts=0, max_attempts=3))
        assert r.decision is GateDecision.LOOP_BACK
        assert "weak test" in (r.feedback or "")

    @pytest.mark.asyncio
    async def test_judge_veto_at_budget_escalates(self) -> None:
        async def det(_c):
            return DetResult(ok=True)

        async def judge(_c, _i):
            return JudgeVerdict(approve=False, feedback="still weak")

        gate = HybridGate("review", deterministic=det, judge=judge)
        r = await gate.evaluate(_ctx(attempts=3, max_attempts=3))
        assert r.decision is GateDecision.ESCALATE

    @pytest.mark.asyncio
    async def test_judge_dispatch_failure_defaults_to_approve(self) -> None:
        async def det(_c):
            return DetResult(ok=True)

        async def judge(_c, _i):
            raise RuntimeError("dispatch boom")

        gate = HybridGate(
            "review", deterministic=det, judge=judge, fail_default_approve=True
        )
        r = await gate.evaluate(_ctx())
        assert r.decision is GateDecision.ADVANCE

    @pytest.mark.asyncio
    async def test_credit_exhaustion_reraises(self) -> None:
        from subprocess_util import CreditExhaustedError  # real location

        async def det(_c):
            return DetResult(ok=True)

        async def judge(_c, _i):
            raise CreditExhaustedError("out of credit")

        gate = HybridGate("review", deterministic=det, judge=judge)
        with pytest.raises(CreditExhaustedError):
            await gate.evaluate(_ctx())

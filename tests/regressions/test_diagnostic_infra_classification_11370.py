"""Regression pins for #11370: failover-lane parse failures are INFRA.

Live incident: with credit failover active (GLM serving spawns), the
diagnostic Stage-1 agent's weaker format compliance produced 'no
structured output' fallbacks, which read as fixable=False and escalated
real, tractable issues to HITL (#11248) — burning human attention on a
harness artifact.

Pins (incl. both fresh-eyes review findings):
1. The REAL diagnose() path: non-JSON output + failover active →
   infra_failure=True; failover inactive → unchanged fallback.
2. The gate parks ("retry") on infra, never escalates.
3. The park DEQUEUES the issue for a cooldown — no respawn per poll
   (the 2026-07-22 retry-storm shape) — and expires cleanly.
4. infra_failure defaults False (field addition is inert elsewhere).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import credit_failover
from diagnostic_loop import DiagnosticLoop
from diagnostic_runner import DiagnosticRunner
from models import DiagnosisResult, EscalationContext, Severity


def _diagnosis(*, infra: bool) -> DiagnosisResult:
    return DiagnosisResult(
        root_cause="raw transcript",
        severity=Severity.P2_FUNCTIONAL,
        fixable=False,
        fix_plan="",
        human_guidance="Agent did not produce structured output.",
        infra_failure=infra,
    )


def _loop() -> DiagnosticLoop:
    loop = object.__new__(DiagnosticLoop)
    loop._config = SimpleNamespace(
        max_diagnostic_attempts=2, credit_failover_cooldown_minutes=15
    )
    loop._escalate_to_hitl = AsyncMock()
    loop._infra_parked = {}
    return loop


def _runner(tmp_path, transcript: str) -> DiagnosticRunner:
    runner = DiagnosticRunner.__new__(DiagnosticRunner)
    runner._config = MagicMock(repo_root=tmp_path)
    runner._mockworld_diagnosis = lambda: None
    runner._build_command = lambda: ["fake-agent"]
    runner._execute = AsyncMock(return_value=transcript)
    return runner


@pytest.mark.asyncio
async def test_diagnose_fallback_marks_infra_under_failover(tmp_path) -> None:
    """The REAL diagnose() wiring: non-JSON + failover active → infra."""
    runner = _runner(tmp_path, "glm prose with no json and no limit signal")
    ctx = EscalationContext(cause="test build failure", origin_phase="implement")
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=15)
    try:
        result = await runner.diagnose(123, "t", "b", ctx)
    finally:
        credit_failover.reset_for_tests()
    assert result.infra_failure is True


@pytest.mark.asyncio
async def test_diagnose_fallback_not_infra_when_failover_inactive(tmp_path) -> None:
    credit_failover.reset_for_tests()
    runner = _runner(tmp_path, "prose with no json and no limit signal")
    ctx = EscalationContext(cause="test build failure", origin_phase="implement")
    result = await runner.diagnose(123, "t", "b", ctx)
    assert result.infra_failure is False
    assert result.fixable is False


@pytest.mark.asyncio
async def test_infra_failure_parks_instead_of_escalating() -> None:
    loop = _loop()
    gated = await loop._check_diagnosis_gates(1, _diagnosis(infra=True), [], "c")
    assert gated == "retry"
    loop._escalate_to_hitl.assert_not_awaited()


@pytest.mark.asyncio
async def test_infra_park_dequeues_until_cooldown() -> None:
    """The park DEQUEUES — no respawn per poll (retry-storm shape) — and
    the cooldown expires cleanly, dropping the entry."""
    loop = _loop()
    gated = await loop._check_diagnosis_gates(7, _diagnosis(infra=True), [], "c")
    assert gated == "retry"
    assert loop._infra_park_active(7) is True
    loop._infra_parked[7] = datetime.now(UTC) - timedelta(minutes=16)
    assert loop._infra_park_active(7) is False
    assert 7 not in loop._infra_parked


@pytest.mark.asyncio
async def test_non_infra_parse_failure_still_escalates() -> None:
    loop = _loop()
    gated = await loop._check_diagnosis_gates(1, _diagnosis(infra=False), [], "c")
    assert gated == "escalated"
    loop._escalate_to_hitl.assert_awaited()


def test_infra_failure_defaults_false() -> None:
    result = DiagnosisResult(
        root_cause="x",
        severity=Severity.P2_FUNCTIONAL,
        fixable=True,
        fix_plan="p",
        human_guidance="",
    )
    assert result.infra_failure is False

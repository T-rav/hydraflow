"""Regression pins for #11370: failover-lane parse failures are INFRA.

Live incident: with credit failover active (GLM serving spawns), the
diagnostic Stage-1 agent's weaker format compliance produced 'no
structured output' fallbacks, which read as fixable=False and escalated
real, tractable issues to HITL (#11248) — burning human attention on a
harness artifact.

Pins:
1. Parse failure while failover is ACTIVE → infra_failure=True → the
   gate parks ("retry"), never escalates, records no attempt.
2. Parse failure while failover is INACTIVE → unchanged behavior
   (fixable=False → escalate).
3. infra_failure defaults False (field addition is inert elsewhere).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import credit_failover
from diagnostic_loop import DiagnosticLoop
from models import DiagnosisResult, Severity


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
    loop._config = SimpleNamespace(max_diagnostic_attempts=2)
    loop._escalate_to_hitl = AsyncMock()
    return loop


@pytest.mark.asyncio
async def test_infra_failure_parks_instead_of_escalating() -> None:
    loop = _loop()
    gated = await loop._check_diagnosis_gates(1, _diagnosis(infra=True), [], "c")
    assert gated == "retry"
    loop._escalate_to_hitl.assert_not_awaited()


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


def test_runner_marks_infra_only_under_failover(monkeypatch) -> None:
    """The diagnose fallback consults credit_failover.is_active()."""
    from datetime import UTC, datetime

    credit_failover.reset_for_tests()
    assert credit_failover.is_active() is False
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=15)
    assert credit_failover.is_active() is True
    credit_failover.reset_for_tests()

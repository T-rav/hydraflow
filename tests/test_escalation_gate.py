"""Tests for escalation_gate.py."""

from __future__ import annotations

from typing import Any

import pytest

from escalation_gate import high_risk_diff_touched, should_escalate_debug

#: The quiescent call — gate on, confident, low risk, no retries: no escalation.
#: Every case below states only what it changes from this baseline.
_QUIET: dict[str, Any] = {
    "enabled": True,
    "confidence": 0.9,
    "confidence_threshold": 0.7,
    "parse_failed": False,
    "retry_count": 0,
    "max_subskill_attempts": 1,
    "risk": "low",
    "high_risk_files_touched": False,
}


@pytest.mark.parametrize(
    ("overrides", "escalate", "reasons"),
    [
        pytest.param({}, False, [], id="no_escalation_when_confident_and_low_risk"),
        pytest.param(
            {"confidence": 0.2},
            True,
            ["low_confidence"],
            id="escalation_on_low_confidence",
        ),
        pytest.param(
            {"confidence": 0.8, "parse_failed": True, "risk": "medium"},
            True,
            ["precheck_parse_failed"],
            id="escalation_on_parse_failure",
        ),
        pytest.param(
            {"enabled": False},
            False,
            ["disabled"],
            id="no_escalation_when_gate_disabled",
        ),
        # A disabled gate reports "disabled" and nothing else, however loud the signals.
        pytest.param(
            {
                "enabled": False,
                "confidence": 0.2,
                "parse_failed": True,
                "retry_count": 5,
                "max_subskill_attempts": 3,
                "risk": "critical",
                "high_risk_files_touched": True,
            },
            False,
            ["disabled"],
            id="disabled_gate_ignores_triggering_signals",
        ),
        pytest.param(
            {"risk": "high"}, True, ["risk_high"], id="escalation_on_high_risk"
        ),
        pytest.param(
            {"risk": "critical"},
            True,
            ["risk_critical"],
            id="escalation_on_critical_risk",
        ),
        pytest.param(
            {"high_risk_files_touched": True},
            True,
            ["high_risk_files"],
            id="escalation_on_high_risk_files_touched",
        ),
        pytest.param(
            {"retry_count": 3, "max_subskill_attempts": 3},
            True,
            ["subskill_retries_exhausted"],
            id="escalation_on_retries_exhausted_at_max",
        ),
        pytest.param(
            {"retry_count": 5, "max_subskill_attempts": 3},
            True,
            ["subskill_retries_exhausted"],
            id="escalation_on_retries_exhausted_above_max",
        ),
        # Below max is not exhausted — the boundary is >=, not >.
        pytest.param(
            {"retry_count": 2, "max_subskill_attempts": 3},
            False,
            [],
            id="no_escalation_when_retries_below_max",
        ),
        # The risk field is normalized: surrounding whitespace and case are ignored.
        pytest.param(
            {"risk": " High "},
            True,
            ["risk_high"],
            id="risk_field_normalized_ignoring_whitespace_and_case",
        ),
        pytest.param({"risk": "medium"}, False, [], id="no_escalation_on_medium_risk"),
        # max_subskill_attempts=0 is the config default, but all production callers
        # guard with `if max_subskill_attempts <= 0: return` before reaching this
        # function. This case exercises the gate's own boundary arithmetic directly:
        # retry_count=0 >= max_subskill_attempts=0 is True, so the signal fires.
        pytest.param(
            {"max_subskill_attempts": 0},
            True,
            ["subskill_retries_exhausted"],
            id="escalation_when_max_attempts_is_zero",
        ),
        # Exactly at the threshold is confident enough — the test is <, not <=.
        pytest.param(
            {"confidence": 0.7},
            False,
            [],
            id="no_escalation_at_exact_confidence_threshold",
        ),
    ],
)
def test_escalation_decision(
    overrides: dict[str, Any], escalate: bool, reasons: list[str]
) -> None:
    decision = should_escalate_debug(**{**_QUIET, **overrides})
    assert decision.escalate is escalate
    assert decision.reasons == reasons


def test_all_signals_active_simultaneously_escalates_with_all_five_reasons() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.3,
        confidence_threshold=0.7,
        parse_failed=True,
        retry_count=5,
        max_subskill_attempts=3,
        risk="critical",
        high_risk_files_touched=True,
    )
    assert decision.escalate is True
    assert len(decision.reasons) == 5
    assert set(decision.reasons) == {
        "precheck_parse_failed",
        "low_confidence",
        "risk_critical",
        "high_risk_files",
        "subskill_retries_exhausted",
    }


def test_no_escalation_when_optional_risk_and_files_omitted() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
    )
    assert decision.escalate is False
    assert decision.reasons == []


# ---------------------------------------------------------------------------
# high_risk_diff_touched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        pytest.param(
            "diff --git a/src/auth/login.py b/src/auth/login.py\n+pass",
            True,
            id="auth_path",
        ),
        pytest.param(
            "diff --git a/src/security/tokens.py b/src/security/tokens.py\n+pass",
            True,
            id="security_path",
        ),
        pytest.param(
            "diff --git a/src/payment/checkout.py b/src/payment/checkout.py\n+pass",
            True,
            id="payment_path",
        ),
        pytest.param(
            "diff --git a/db/migration_001.sql b/db/migration_001.sql\n+CREATE TABLE;",
            True,
            id="migration",
        ),
        pytest.param(
            "diff --git a/infra/deploy.yml b/infra/deploy.yml\n+step: deploy",
            True,
            id="infra_path",
        ),
        # The negative case: an ordinary source file must NOT trip the gate.
        pytest.param(
            "diff --git a/src/utils.py b/src/utils.py\n+def helper(): pass",
            False,
            id="safe_diff",
        ),
        # Same auth path, mixed case — path matching is case-insensitive.
        pytest.param(
            "diff --git a/src/Auth/Login.py b/src/Auth/Login.py\n+pass",
            True,
            id="case_insensitive",
        ),
    ],
)
def test_high_risk_diff_touched(diff: str, expected: bool) -> None:
    assert high_risk_diff_touched(diff) is expected

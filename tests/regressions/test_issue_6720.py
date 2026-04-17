"""Regression test for issue #6720.

Bug: ``DiagnosticRunner.diagnose()`` catches ``Exception`` on
``DiagnosisResult.model_validate(parsed)`` (line 143-154) without logging
the ``ValidationError`` details.  When an LLM returns JSON that parses but
violates the Pydantic schema (e.g. invalid severity enum), the fallback
``DiagnosisResult`` is returned but the *reason* for the validation failure
is invisible — no log record, no ``exc_info``, no field-level detail.

This makes it impossible to detect or debug schema drift between the LLM
prompt and the Pydantic model.

Expected behaviour after fix:
  - A WARNING-level log record is emitted with ``exc_info=True`` so the
    ``pydantic.ValidationError`` traceback (including which fields failed
    and why) is visible in operator logs.
  - The fallback ``DiagnosisResult`` is still returned (non-blocking).
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from models import DiagnosisResult, EscalationContext, Severity


@pytest.fixture
def runner():
    from diagnostic_runner import DiagnosticRunner

    config = MagicMock()
    config.repo_root = "/tmp/repo"
    config.implementation_tool = "claude"
    config.model = "claude-opus-4-5"
    bus = MagicMock()
    return DiagnosticRunner(config=config, event_bus=bus)


@pytest.fixture
def escalation_ctx():
    return EscalationContext(cause="CI failed", origin_phase="review")


class TestModelValidateErrorNotSwallowed:
    """Issue #6720 — model_validate ValidationError must be logged, not swallowed."""

    @pytest.mark.asyncio
    async def test_validation_error_produces_warning_with_exc_info(
        self, runner, escalation_ctx, monkeypatch, caplog
    ) -> None:
        """When ``model_validate`` raises ``ValidationError`` due to an
        invalid enum value, a WARNING+ log record with ``exc_info=True``
        must be emitted so the Pydantic field-level detail is visible.

        RED today — the except block at diagnostic_runner.py:145 has no
        logging at all.
        """
        invalid_payload = json.dumps(
            {
                "root_cause": "Something broke",
                "severity": "CATASTROPHIC",  # not a valid Severity value
                "fixable": True,
                "fix_plan": "Rewrite everything",
                "human_guidance": "Good luck",
            }
        )

        async def fake_execute(*_args, **_kwargs):
            return f"```json\n{invalid_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.diagnostic"):
            result = await runner.diagnose(
                issue_number=6720,
                issue_title="Schema drift",
                issue_body="LLM output doesn't match model",
                context=escalation_ctx,
            )

        # Fallback is returned (existing, correct behaviour).
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert "did not validate" in result.human_guidance

        # Bug assertion: a WARNING+ log must exist from the diagnostic logger.
        diag_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "hydraflow.diagnostic" in r.name
        ]
        assert diag_warnings, (
            "No WARNING+ log emitted by hydraflow.diagnostic when "
            "model_validate raised ValidationError. The except block at "
            "diagnostic_runner.py:145 swallows the error silently (issue #6720)."
        )

        # The log record must carry exc_info so the full ValidationError
        # traceback (field names, values, constraint violations) is visible.
        record = diag_warnings[0]
        assert record.exc_info is not None and record.exc_info[1] is not None, (
            "Log record must include exc_info with the ValidationError so "
            "operators can see which fields failed and why. "
            f"Got exc_info={record.exc_info!r}"
        )
        assert isinstance(record.exc_info[1], ValidationError), (
            "exc_info should carry a pydantic.ValidationError, "
            f"got {type(record.exc_info[1])}"
        )

    @pytest.mark.asyncio
    async def test_validation_error_log_contains_issue_number(
        self, runner, escalation_ctx, monkeypatch, caplog
    ) -> None:
        """The log message should reference the issue number for traceability.

        RED today — no log is emitted at all.
        """
        bad_payload = json.dumps(
            {
                "root_cause": "test",
                "severity": "NOT_REAL",
                "fixable": "not-a-bool",  # also wrong type
                "fix_plan": "test",
                "human_guidance": "test",
            }
        )

        async def fake_execute(*_args, **_kwargs):
            return f"```json\n{bad_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.diagnostic"):
            await runner.diagnose(
                issue_number=9999,
                issue_title="Test",
                issue_body="Body",
                context=escalation_ctx,
            )

        diag_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "hydraflow.diagnostic" in r.name
        ]
        assert diag_warnings, (
            "No WARNING+ log emitted when model_validate failed (issue #6720)."
        )
        assert "9999" in diag_warnings[0].getMessage(), (
            "Log message should contain the issue number for traceability, "
            f"got: {diag_warnings[0].getMessage()!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_preserves_parseable_fields(
        self, runner, escalation_ctx, monkeypatch
    ) -> None:
        """The fallback should still extract ``root_cause`` and ``fix_plan``
        from the parsed dict even when validation fails.

        GREEN today — guards against over-correction that drops partial data.
        """
        partial_payload = json.dumps(
            {
                "root_cause": "Disk full",
                "severity": "BOGUS",
                "fixable": True,
                "fix_plan": "Free up space",
                "human_guidance": "Check /var/log",
            }
        )

        async def fake_execute(*_args, **_kwargs):
            return f"```json\n{partial_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        result = await runner.diagnose(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            context=escalation_ctx,
        )

        assert result.root_cause == "Disk full"
        assert result.fix_plan == "Free up space"
        assert result.severity == Severity.P2_FUNCTIONAL

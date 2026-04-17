"""Regression test for issue #6558.

Bug: ``DiagnosticRunner.diagnose()`` at lines 143-154 catches ``Exception``
on ``DiagnosisResult.model_validate(parsed)`` without logging the exception.
Pydantic ``ValidationError`` carries field-level detail (which field failed,
what value was received) that operators need to diagnose format drift.  The
current code silently returns a fallback ``DiagnosisResult`` with
``human_guidance="Agent output did not validate. Manual review required."``
but writes *nothing* to the log — no warning, no traceback, no field info.

Expected behaviour after fix:
  - ``logger.warning("DiagnosisResult validation failed", exc_info=True)``
    (or equivalent) is called inside the ``except`` block so operators can
    see which field caused the failure.
  - The fallback ``DiagnosisResult`` is still returned (non-blocking).

This test asserts the *correct* behaviour, so it is RED against the current
buggy code.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

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


class TestValidationErrorIsLogged:
    """Issue #6558 — Pydantic ValidationError must be logged, not swallowed."""

    @pytest.mark.asyncio
    async def test_validation_error_is_logged_at_warning(
        self, runner, monkeypatch, caplog
    ) -> None:
        """When ``model_validate`` raises a ``ValidationError``, the except
        block must log the error at WARNING (or higher) with ``exc_info``.

        Currently FAILS (RED) because the ``except Exception`` block at
        line 145 contains no logging at all.
        """
        # Arrange — agent returns JSON that parses but fails model_validate
        # ("severity": "INVALID" is not a valid Severity enum value)
        invalid_json = json.dumps(
            {
                "root_cause": "Some cause",
                "severity": "INVALID",
                "fixable": True,
                "fix_plan": "Some plan",
                "human_guidance": "Some guidance",
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{invalid_json}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        # Act — capture logs from the diagnostic logger
        with caplog.at_level(logging.DEBUG, logger="hydraflow.diagnostic"):
            result = await runner.diagnose(
                issue_number=42,
                issue_title="Bug",
                issue_body="Fix it",
                context=ctx,
            )

        # Assert — the fallback is returned (existing behaviour, should stay)
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert "did not validate" in result.human_guidance

        # Assert — the ValidationError was logged (the bug: this fails today)
        validation_logs = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "hydraflow.diagnostic" in r.name
        ]
        assert len(validation_logs) >= 1, (
            "Expected at least one WARNING+ log from hydraflow.diagnostic "
            "when model_validate raises ValidationError, but got none. "
            "The except block at diagnostic_runner.py:145 swallows the error silently."
        )

        # The log record should include exc_info so the Pydantic field-level
        # detail appears in the traceback.
        logged = validation_logs[0]
        assert logged.exc_info is not None and logged.exc_info[1] is not None, (
            "The log record must include exc_info so that the Pydantic "
            "ValidationError traceback (with field-level detail) is visible "
            f"to operators. Got exc_info={logged.exc_info!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_still_returned_on_validation_error(
        self, runner, monkeypatch
    ) -> None:
        """After the fix, the fallback DiagnosisResult must still be returned
        (non-blocking).  This is GREEN today and must stay GREEN — it guards
        against an over-correction that re-raises instead of logging.
        """
        # Arrange — missing required fields triggers ValidationError
        bad_json = json.dumps({"root_cause": "Partial", "severity": "INVALID"})

        async def fake_execute(*args, **kwargs):
            return f"```json\n{bad_json}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        # Act
        result = await runner.diagnose(
            issue_number=99,
            issue_title="Test",
            issue_body="Body",
            context=ctx,
        )

        # Assert — fallback result, not a raised exception
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert result.severity == Severity.P2_FUNCTIONAL
        assert result.root_cause == "Partial"

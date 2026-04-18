"""Regression test for issue #6624.

DiagnosticRunner.diagnose() catches ``Exception`` broadly around
``DiagnosisResult.model_validate(parsed)`` and returns a hard-coded
P2_FUNCTIONAL fallback *without logging the validation error*.  This
makes schema mismatches completely invisible — there is no way to
distinguish "JSON parsed but failed Pydantic validation" from "agent
crashed" without reading source code.

These tests will fail (RED) until the except block emits at least a
``logger.warning`` with ``exc_info=True`` before returning the fallback.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

from models import EscalationContext, Severity


@pytest.fixture
def runner():
    from diagnostic_runner import DiagnosticRunner

    config = MagicMock()
    config.repo_root = "/tmp/repo"
    config.implementation_tool = "claude"
    config.model = "claude-opus-4-5"
    bus = MagicMock()
    return DiagnosticRunner(config=config, event_bus=bus)


# ---------------------------------------------------------------------------
# Test 1 — ValidationError must be logged, not swallowed
# ---------------------------------------------------------------------------


class TestValidationErrorIsLogged:
    """When model_validate raises ValidationError the runner must log it."""

    @pytest.mark.asyncio
    async def test_validation_error_emits_warning(
        self, runner, monkeypatch, caplog
    ) -> None:
        """Feed agent output with valid JSON but an invalid severity value so
        ``DiagnosisResult.model_validate`` raises ``ValidationError``.

        The runner currently swallows the exception silently and returns a
        P2_FUNCTIONAL fallback.  This test asserts that a WARNING (or higher)
        log record is emitted that mentions the validation failure — proving
        the bug when it fails.
        """
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        # Valid JSON, but "INVALID" is not a valid Severity value →
        # model_validate will raise ValidationError.
        bad_payload = json.dumps(
            {
                "root_cause": "Something broke",
                "severity": "INVALID",
                "fixable": True,
                "fix_plan": "Do stuff",
                "human_guidance": "Guidance",
                "affected_files": [],
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{bad_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        with caplog.at_level(logging.WARNING, logger="hydraflow.diagnostic"):
            result = await runner.diagnose(
                issue_number=99,
                issue_title="Schema mismatch",
                issue_body="Body",
                context=ctx,
            )

        # Sanity: the fallback path was taken
        assert result.fixable is False
        assert result.severity == Severity.P2_FUNCTIONAL

        # BUG ASSERTION: there must be a warning about the validation failure.
        # Currently the except block has no logging, so this will fail.
        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name == "hydraflow.diagnostic"
        ]
        assert warning_messages, (
            "DiagnosticRunner.diagnose() swallowed a ValidationError without "
            "logging — validation failures are invisible (issue #6624)"
        )


# ---------------------------------------------------------------------------
# Test 2 — Warning log must include issue number for traceability
# ---------------------------------------------------------------------------


class TestValidationWarningIncludesIssueNumber:
    """The warning log must reference the issue number for traceability."""

    @pytest.mark.asyncio
    async def test_warning_contains_issue_number(
        self, runner, monkeypatch, caplog
    ) -> None:
        """Even if a warning is added, it must include the issue number so
        operators can correlate the log line to the affected issue.
        """
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        bad_payload = json.dumps(
            {
                "root_cause": "Something broke",
                "severity": "INVALID",
                "fixable": True,
                "fix_plan": "Do stuff",
                "human_guidance": "Guidance",
                "affected_files": [],
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{bad_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        with caplog.at_level(logging.WARNING, logger="hydraflow.diagnostic"):
            await runner.diagnose(
                issue_number=42,
                issue_title="Schema mismatch",
                issue_body="Body",
                context=ctx,
            )

        warning_texts = " ".join(
            r.message
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name == "hydraflow.diagnostic"
        )
        assert "42" in warning_texts, (
            "Validation warning must include the issue number for "
            "traceability — got no mention of issue #42 (issue #6624)"
        )


# ---------------------------------------------------------------------------
# Test 3 — Warning log must include exc_info for debuggability
# ---------------------------------------------------------------------------


class TestValidationWarningIncludesExcInfo:
    """The warning log must include exc_info so the traceback is visible."""

    @pytest.mark.asyncio
    async def test_warning_has_exc_info(self, runner, monkeypatch, caplog) -> None:
        """Acceptance criteria require ``exc_info=True`` so the full
        ValidationError traceback appears in structured logging output.
        """
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        bad_payload = json.dumps(
            {
                "root_cause": "Something broke",
                "severity": "INVALID",
                "fixable": True,
                "fix_plan": "Do stuff",
                "human_guidance": "Guidance",
                "affected_files": [],
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{bad_payload}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)

        with caplog.at_level(logging.WARNING, logger="hydraflow.diagnostic"):
            await runner.diagnose(
                issue_number=1,
                issue_title="Schema mismatch",
                issue_body="Body",
                context=ctx,
            )

        warning_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name == "hydraflow.diagnostic"
        ]
        assert warning_records, (
            "No warning logged at all — cannot check exc_info (issue #6624)"
        )
        # exc_info is a 3-tuple (type, value, tb) when set, or None/False
        has_exc_info = any(
            r.exc_info and r.exc_info[0] is not None for r in warning_records
        )
        assert has_exc_info, (
            "Validation warning was logged but without exc_info=True — "
            "the ValidationError traceback is not visible (issue #6624)"
        )

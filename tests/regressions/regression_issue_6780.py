"""Regression test for issue #6780.

Bug 1: ``pr_manager.py:1103`` — ``tempfile.mkstemp()`` returns an open fd
that is passed to ``os.fdopen(fd, "wb")``.  If ``os.fdopen`` itself raises
(e.g. due to an invalid mode or an OS-level error), the fd from ``mkstemp``
is never closed, causing a file-descriptor leak.  The ``finally`` block only
unlinks the file path but does not close the fd.

Bug 2: ``diagnostic_runner.py:145`` — ``except Exception`` when
``DiagnosisResult.model_validate(parsed)`` raises a ``ValidationError``
constructs a fallback ``DiagnosisResult`` without logging the validation
error.  Operators have no way to see *which* field failed or *what* value
was rejected.

Expected behaviour after fix:

  Bug 1: If ``os.fdopen`` raises, the fd from ``mkstemp`` is closed before
  the exception propagates.

  Bug 2: A ``logger.warning(…, exc_info=True)`` (or equivalent) is emitted
  inside the ``except`` block so the Pydantic ``ValidationError`` traceback
  is visible in logs.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current buggy code.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus
from models import DiagnosisResult, EscalationContext
from pr_manager import PRManager
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager() -> PRManager:
    """Build a PRManager with a valid repo slug so _assert_repo passes."""
    config = ConfigFactory.create(repo="test-owner/test-repo")
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return PRManager(config, bus)


# ---------------------------------------------------------------------------
# Bug 1 — fd leak in upload_screenshot_gist when os.fdopen raises
# ---------------------------------------------------------------------------


class TestFdLeakOnFdopenFailure:
    """Issue #6780 — ``upload_screenshot_gist`` must close the fd from
    ``tempfile.mkstemp`` if ``os.fdopen`` raises.

    Currently FAILS (RED) because the ``except Exception`` block at
    line 1119 catches the error and returns ``""``, but the fd is never
    closed — only the file path is unlinked in the ``finally`` block.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6780 — fix not yet landed", strict=False)
    async def test_fd_is_closed_when_fdopen_raises(self) -> None:
        """Create a real fd via os.pipe, mock mkstemp to return it, make
        os.fdopen raise, then verify the fd was properly closed."""
        pm = _make_pr_manager()

        # Create a real fd we can track — use a real temp file so unlink works
        real_fd, real_path = tempfile.mkstemp(suffix=".png", prefix="test-6780-")

        # A minimal valid base64-encoded PNG (1x1 transparent pixel)
        png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50).decode()

        original_fdopen = os.fdopen

        def failing_fdopen(fd, *args, **kwargs):
            """Raise OSError only for our tracked fd."""
            if fd == real_fd:
                raise OSError("Simulated fdopen failure")
            return original_fdopen(fd, *args, **kwargs)

        with (
            patch("pr_manager.tempfile.mkstemp", return_value=(real_fd, real_path)),
            patch("pr_manager.os.fdopen", side_effect=failing_fdopen),
        ):
            result = await pm.upload_screenshot_gist(png_b64)

        # The method should return "" on failure (existing behaviour)
        assert result == ""

        # The fd from mkstemp MUST have been closed.
        # If the bug exists, the fd is still open and os.fstat succeeds.
        try:
            with pytest.raises(OSError):
                os.fstat(real_fd)
        finally:
            # Clean up the leaked fd so the test process doesn't leak it
            try:
                os.close(real_fd)
            except OSError:
                pass  # already closed — the fix worked

    @pytest.mark.asyncio
    async def test_fd_is_closed_on_successful_path(self) -> None:
        """Sanity check: on a normal (non-fdopen-failing) path the fd is
        still properly closed via the ``with os.fdopen(...)`` context manager.
        This test should pass on current code and remain green after the fix.
        """
        pm = _make_pr_manager()

        real_fd, real_path = tempfile.mkstemp(suffix=".png", prefix="test-6780-ok-")
        png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50).decode()

        async def fake_run_gh(*args, **kwargs):
            return "https://gist.github.com/abc123"

        with (
            patch("pr_manager.tempfile.mkstemp", return_value=(real_fd, real_path)),
            patch.object(pm, "_run_gh", side_effect=fake_run_gh),
        ):
            await pm.upload_screenshot_gist(png_b64)

        # fd must be closed after normal execution too
        with pytest.raises(OSError):
            os.fstat(real_fd)


# ---------------------------------------------------------------------------
# Bug 2 — diagnostic_runner silently swallows validation errors
# ---------------------------------------------------------------------------


class TestDiagnosisValidationErrorNotLogged:
    """Issue #6780 — ``DiagnosticRunner.diagnose()`` must log the Pydantic
    ``ValidationError`` when ``model_validate`` fails at line 145.

    Currently FAILS (RED) because the ``except Exception`` block constructs
    a fallback ``DiagnosisResult`` without any logging.
    """

    @pytest.fixture
    def runner(self):
        from diagnostic_runner import DiagnosticRunner

        config = MagicMock()
        config.repo_root = "/tmp/repo"
        config.implementation_tool = "claude"
        config.model = "claude-opus-4-5"
        bus = MagicMock()
        return DiagnosticRunner(config=config, event_bus=bus)

    @pytest.mark.asyncio
    async def test_validation_error_produces_warning_log(
        self, runner, monkeypatch, caplog
    ) -> None:
        """When ``model_validate`` raises a ``ValidationError`` the except
        block must log at WARNING+ with ``exc_info`` so the Pydantic
        field-level detail is observable.

        Currently FAILS: the except block at line 145 has no logging.
        """
        # Arrange — agent returns JSON that parses but fails model_validate
        # "severity": "BOGUS" is not a valid Severity enum value
        invalid_json = json.dumps(
            {
                "root_cause": "Some root cause",
                "severity": "BOGUS",
                "fixable": True,
                "fix_plan": "Some plan",
                "human_guidance": "Some guidance",
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{invalid_json}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        # Act
        with caplog.at_level(logging.DEBUG, logger="hydraflow.diagnostic"):
            result = await runner.diagnose(
                issue_number=99,
                issue_title="Test bug",
                issue_body="Test body",
                context=ctx,
            )

        # Assert — fallback result is returned (existing behaviour, should stay)
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert "did not validate" in result.human_guidance

        # Assert — the ValidationError was logged (the bug: this fails today)
        warning_logs = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "hydraflow.diagnostic" in r.name
        ]
        assert len(warning_logs) >= 1, (
            "Expected at least one WARNING+ log from hydraflow.diagnostic "
            "when model_validate raises ValidationError, but got none. "
            "The except block at diagnostic_runner.py:145 swallows the error "
            "silently — operators cannot see which field failed."
        )

        # The log record must include exc_info so the Pydantic traceback
        # with field-level detail is visible.
        logged = warning_logs[0]
        assert logged.exc_info is not None and logged.exc_info[1] is not None, (
            "The log record must include exc_info so that the Pydantic "
            "ValidationError traceback (with field-level detail) is visible "
            f"to operators. Got exc_info={logged.exc_info!r}"
        )

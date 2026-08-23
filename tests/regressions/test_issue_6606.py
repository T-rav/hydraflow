"""Regression test for issue #6606.

Bug: ``DiagnosticLoop._do_work`` catches **all** ``Exception`` subclasses
when ``list_issues_by_label`` fails (line 95).  Because
``AuthenticationError`` is a subclass of ``RuntimeError`` (and thus
``Exception``), authentication failures are silently swallowed — the loop
returns ``{"processed": 0, ...}`` as if no issues existed, and the caller
never learns that credentials are broken.

Expected behaviour after fix:
  - ``AuthenticationError`` propagates out of ``_do_work`` so the loop
    supervisor can handle it (alert, back off, etc.).
  - Other transient ``Exception`` subclasses are still caught gracefully.

Note on finding #1 (exc_info on runner.fix crash): the code at lines
231-234 already uses ``logger.exception()``, which inherently captures
``exc_info``.  That part of the issue is already correct and the
corresponding test below documents the desired behaviour (GREEN).

These tests are RED against the current buggy code for finding #2.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from diagnostic_loop import DiagnosticLoop  # noqa: E402
from models import DiagnosisResult, EscalationContext, Severity  # noqa: E402
from subprocess_util import AuthenticationError  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers — mirrors test_diagnostic_loop.py factory
# ---------------------------------------------------------------------------


def _make_diagnosis(*, fixable: bool = True) -> DiagnosisResult:
    return DiagnosisResult(
        root_cause="test root cause",
        severity=Severity.P2_FUNCTIONAL,
        fixable=fixable,
        fix_plan="Apply the fix",
        human_guidance="Check the logs",
        affected_files=["src/foo.py"],
    )


def _make_loop(
    tmp_path: Path,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock]:
    """Build a DiagnosticLoop with test-friendly mocks.

    Returns (loop, runner_mock, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)
    # DiagnosticLoop now defaults OFF (#9895); these tests exercise its _do_work
    # logic, so enable the deploy-time kill-switch for the test config.
    object.__setattr__(deps.config, "diagnostic_loop_enabled", True)

    runner = MagicMock()
    runner.diagnose = AsyncMock(return_value=_make_diagnosis())
    runner.fix = AsyncMock(return_value=(True, "fixed"))

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(
        return_value=EscalationContext(cause="ci_failure", origin_phase="review")
    )
    state.get_diagnostic_attempts = MagicMock(return_value=[])
    state.add_diagnostic_attempt = MagicMock()
    state.set_diagnosis_severity = MagicMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, runner, prs, state


# ---------------------------------------------------------------------------
# Finding #2 — AuthenticationError silently swallowed at line 95
# ---------------------------------------------------------------------------


class TestAuthenticationErrorNotSwallowed:
    """Issue #6606 — ``AuthenticationError`` on label fetch must propagate,
    not be caught by the broad ``except Exception`` at line 95.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_propagates_from_do_work(
        self, tmp_path: Path
    ) -> None:
        """When ``list_issues_by_label`` raises ``AuthenticationError``,
        ``_do_work`` must let it propagate rather than returning zero-counts.

        Currently FAILS (RED) because the broad ``except Exception`` at
        line 95 catches ``AuthenticationError`` and silently returns
        ``{"processed": 0, ...}``.
        """
        loop, _, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_transient_error_still_caught_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A non-auth ``Exception`` (e.g. network timeout) should still be
        caught and the method should return zero-counts.

        This is GREEN on the current code and should remain GREEN after fix.
        """
        loop, _, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.side_effect = RuntimeError("network timeout")

        result = await loop._do_work()

        assert result == {"processed": 0, "fixed": 0, "escalated": 0, "retried": 0}


# ---------------------------------------------------------------------------
# Finding #1 — logger.exception on runner.fix() crash (already correct)
# ---------------------------------------------------------------------------


class TestRunnerFixCrashLogsExcInfo:
    """Issue #6606 finding #1 — verify ``runner.fix()`` crash path captures
    exc_info via ``logger.exception()``.

    The current code already uses ``logger.exception()`` at line 232, so
    this test is GREEN.  It documents the desired behaviour.
    """

    @pytest.mark.asyncio
    async def test_runner_fix_crash_logs_with_exc_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When ``runner.fix()`` raises, the exception handler must log with
        ``exc_info`` so the stack trace is captured.
        """
        loop, runner, prs, state = _make_loop(tmp_path)

        # Set up an issue to process
        prs.list_issues_by_label.return_value = [
            {"number": 42, "title": "broken", "body": "details"}
        ]
        # runner.fix() crashes. The stand-in is deliberately RuntimeError, not
        # ValueError: #6752/#6809 made LIKELY_BUG_EXCEPTIONS (which includes
        # ValueError) propagate out of this handler rather than be logged and
        # swallowed, so a likely-bug stand-in would never reach the log line
        # this test is about. #6606's finding is that the crash path captures
        # exc_info -- that is unchanged, and is what this asserts. The
        # propagate-instead-of-swallow contract is pinned by the sibling test
        # below, so neither guarantee rests on the other's stand-in.
        runner.fix.side_effect = RuntimeError("something broke inside fix")

        with caplog.at_level(logging.ERROR, logger="hydraflow.diagnostic_loop"):
            await loop._do_work()

        # Find the log record for the crash
        crash_records = [
            r for r in caplog.records if "runner.fix() crashed" in r.getMessage()
        ]
        assert crash_records, (
            "Expected a log record mentioning 'runner.fix() crashed' but none found"
        )
        record = crash_records[0]
        assert record.exc_info is not None, (
            "runner.fix() crash was logged WITHOUT exc_info — stack trace is lost. "
            "Use logger.exception() or pass exc_info=True (issue #6606)"
        )
        assert record.exc_info[1] is not None, (
            "exc_info was set but exception instance is None"
        )

    @pytest.mark.asyncio
    async def test_a_likely_bug_from_runner_fix_propagates_instead(
        self, tmp_path: Path
    ) -> None:
        """The other half of the contract (#6752/#6809, landed by #11668).

        A ``ValueError`` from ``runner.fix()`` is a probable defect in our own
        code, not a transient failure of the work. It used to be logged as
        "runner.fix() crashed" and filed as a failed fix, so the loop moved on
        to the next issue and the bug stayed invisible. It now propagates.
        """
        loop, runner, prs, _state = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = [
            {"number": 42, "title": "broken", "body": "details"}
        ]
        runner.fix.side_effect = ValueError("a real bug, not a flaky fix")

        with pytest.raises(ValueError, match="a real bug"):
            await loop._do_work()

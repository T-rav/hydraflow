"""Regression test for issue #6411.

Bug: ``DiagnosticLoop._process_issue`` has ``except Exception`` (line 231)
that catches ``PermissionError`` raised by ``diagnostic_runner.fix()``.

``PermissionError`` is a subclass of ``Exception``, so it gets caught and
silently converted to ``success=False, transcript="runner.fix() crashed"``
instead of propagating as a fatal infrastructure error.

This means:
  - The diagnostic loop wastes its attempt budget retrying a permanent
    infra error (e.g. filesystem permission denied).
  - The issue eventually escalates to HITL as a "failed fix" rather than
    surfacing the real infrastructure problem.

Expected behaviour after fix:
  - ``PermissionError`` from ``runner.fix()`` propagates out of
    ``_process_issue`` rather than being silently swallowed.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from diagnostic_loop import DiagnosticLoop
from models import DiagnosisResult, EscalationContext, Severity
from tests.helpers import make_bg_loop_deps


def _make_diagnosis(
    *,
    fixable: bool = True,
    severity: Severity = Severity.P2_FUNCTIONAL,
) -> DiagnosisResult:
    """Build a DiagnosisResult with test-friendly defaults."""
    return DiagnosisResult(
        root_cause="Test root cause",
        severity=severity,
        fixable=fixable,
        fix_plan="Apply the fix",
        human_guidance="Check the logs",
        affected_files=["src/foo.py"],
    )


def _make_context() -> EscalationContext:
    return EscalationContext(cause="ci_failure", origin_phase="review")


def _make_loop(
    tmp_path: Path,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock]:
    """Build a DiagnosticLoop with test-friendly defaults.

    Returns (loop, runner_mock, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    runner = MagicMock()
    runner.diagnose = AsyncMock(return_value=_make_diagnosis())
    runner.fix = AsyncMock(return_value=(True, "fixed successfully"))

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=_make_context())
    state.get_diagnostic_attempts = MagicMock(return_value=[])
    state.add_diagnostic_attempt = MagicMock()
    state.set_diagnosis_severity = MagicMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        workspaces=None,
    )
    return loop, runner, prs, state


class TestPermissionErrorNotSwallowed:
    """PermissionError from runner.fix() must propagate, not be silently caught."""

    @pytest.mark.asyncio
    async def test_permission_error_propagates_from_fix(self, tmp_path: Path) -> None:
        """PermissionError raised by runner.fix() must NOT be caught.

        Current buggy code: ``except Exception`` on line 231 catches
        PermissionError and converts it to ``success=False``.
        This test is RED until PermissionError is re-raised.
        """
        loop, runner, prs, state = _make_loop(tmp_path)
        runner.fix.side_effect = PermissionError("filesystem access denied")

        with pytest.raises(PermissionError, match="filesystem access denied"):
            await loop._process_issue(42, "Bug title", "Bug body")

    @pytest.mark.asyncio
    async def test_permission_error_not_recorded_as_failed_attempt(
        self, tmp_path: Path
    ) -> None:
        """PermissionError should not be recorded as a diagnostic attempt.

        Current buggy code: the error is caught, success=False is set,
        and a failed AttemptRecord is added. This wastes attempt budget
        on a permanent infra error.
        """
        loop, runner, prs, state = _make_loop(tmp_path)
        runner.fix.side_effect = PermissionError("filesystem access denied")

        try:
            await loop._process_issue(42, "Bug title", "Bug body")
        except PermissionError:
            pass  # Expected after fix

        # If PermissionError propagated correctly, no attempt should be recorded
        state.add_diagnostic_attempt.assert_not_called()

    @pytest.mark.asyncio
    async def test_permission_error_does_not_produce_fixed_or_retried(
        self, tmp_path: Path
    ) -> None:
        """PermissionError must not result in a 'retried' or 'fixed' outcome.

        Current buggy code: swallows the error and returns 'retried',
        pretending the fix simply failed. This test verifies the error
        propagates instead of returning a misleading outcome string.
        """
        loop, runner, prs, state = _make_loop(tmp_path)
        runner.fix.side_effect = PermissionError("filesystem access denied")

        # After fix: PermissionError propagates, _process_issue never returns
        with pytest.raises(PermissionError):
            result = await loop._process_issue(42, "Bug title", "Bug body")
            # If we get here, the error was swallowed — fail explicitly
            pytest.fail(
                f"PermissionError was silently caught; "
                f"_process_issue returned {result!r} instead of raising"
            )

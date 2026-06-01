"""Regression test for issue #6490.

Bug: ``ReportIssueLoop._do_work()`` has a bare ``except Exception`` block
(lines 331-332) that catches agent execution failures and logs them, but
falls through without updating the tracked report status to ``"failed"``.

Because ``issue_number`` stays 0, the code falls into the retry path which
sets the tracked report back to ``"queued"`` — silently swallowing the
exception.  The report cycles through processing/queued states indefinitely
instead of being marked as failed.

Expected behaviour after fix:
  - On a non-``AuthenticationRetryError`` exception from the agent, the
    tracked report status is set to ``"failed"`` (not ``"queued"``).
  - The report is not silently retried as if it were a benign "no issue URL
    in transcript" failure.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import PendingReport, TrackedReport
from report_issue_loop import ReportIssueLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
) -> tuple[ReportIssueLoop, StateTracker, MagicMock]:
    """Build a ReportIssueLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path)

    state = StateTracker(tmp_path / "state.json")
    pr_manager = MagicMock()
    pr_manager.upload_screenshot = AsyncMock(return_value="")
    pr_manager.upload_screenshot_gist = AsyncMock(return_value="")
    pr_manager.create_issue = AsyncMock(return_value=123)
    pr_manager.add_labels = AsyncMock()
    pr_manager._run_gh = AsyncMock(return_value='{"labels":[],"body":""}')
    pr_manager._repo = "owner/repo"
    runner = MagicMock()

    loop = ReportIssueLoop(
        config=deps.config,
        state=state,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
        runner=runner,
    )
    return loop, state, pr_manager


class TestAgentExceptionMarksReportFailed:
    """Issue #6490: agent exception should mark tracked report as 'failed'."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6490 — fix not yet landed", strict=False)
    async def test_tracked_report_status_is_failed_on_agent_exception(
        self, tmp_path: Path
    ) -> None:
        """When stream_claude_process raises, the tracked report must transition
        to 'failed' — not silently revert to 'queued' for retry.

        Current (buggy) behaviour: the except block logs and falls through to
        the retry path, which sets status back to 'queued'.
        Expected: status is 'failed'.
        """
        loop, state, _pr = _make_loop(tmp_path)

        report = PendingReport(description="Agent will crash")
        state.enqueue_report(report)

        # Add a tracked report so status transitions are observable.
        tracked = TrackedReport(
            id=report.id,
            reporter_id="test-user",
            description=report.description,
        )
        state.add_tracked_report(tracked)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent crashed unexpectedly")
            await loop._do_work()

        updated = state.get_tracked_report(report.id)
        assert updated is not None, "TrackedReport should still exist"
        # BUG: currently the report status is "queued" (retry path) instead
        # of "failed".  This assertion will FAIL until the bug is fixed.
        assert updated.status == "failed", (
            f"Expected tracked report status 'failed' after agent exception, "
            f"got '{updated.status}'"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6490 — fix not yet landed", strict=False)
    async def test_agent_exception_does_not_increment_retry_attempts(
        self, tmp_path: Path
    ) -> None:
        """A crash-exception should not be treated as a normal retry attempt.

        Current (buggy) behaviour: the fallthrough path calls fail_report()
        which increments the attempt counter — treating an agent crash
        identically to 'agent ran successfully but produced no issue URL'.
        Expected: report is marked failed without incrementing attempts.
        """
        loop, state, _pr = _make_loop(tmp_path)

        report = PendingReport(description="Agent will crash")
        state.enqueue_report(report)

        tracked = TrackedReport(
            id=report.id,
            reporter_id="test-user",
            description=report.description,
        )
        state.add_tracked_report(tracked)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("agent crashed unexpectedly")
            await loop._do_work()

        # The pending report should not have its attempts incremented by the
        # retry path — the exception should be handled distinctly.
        pending = state.peek_report()
        if pending is not None:
            assert pending.attempts == 0, (
                f"Expected attempts to remain 0 after agent exception (report "
                f"should be marked failed, not retried), got {pending.attempts}"
            )

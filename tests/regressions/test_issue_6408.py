"""Regression test for issue #6408.

Bug: ``ReportIssueLoop._do_work`` catches ``except Exception`` on line 331
and falls through with ``issue_number = 0``.  The caller receives the same
return dict (``{"processed": 0, "error": True, ...}``) whether:

  (a) the agent ran normally but produced no issue (no URL in transcript), or
  (b) the agent crashed with an unhandled exception.

This means the caller cannot distinguish a crash from a genuine no-issue
result.  The attempt counter burns down identically for both cases, so
agent crashes consume the retry budget and can escalate to HITL for
reasons unrelated to the agent's actual logic.

Expected behaviour after fix:
  - The return dict from _do_work includes a signal (e.g. ``"agent_crashed"``
    or a distinct ``"error"`` value) when an exception was swallowed.
  - The two code paths produce distinguishable results.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import PendingReport
from report_issue_loop import ReportIssueLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
) -> tuple[ReportIssueLoop, StateTracker]:
    """Build a ReportIssueLoop with test-friendly mocks."""
    deps = make_bg_loop_deps(tmp_path)
    state = StateTracker(tmp_path / "state.json")
    pr_manager = MagicMock()
    pr_manager.upload_screenshot = AsyncMock(return_value="")
    pr_manager.create_issue = AsyncMock(return_value=123)
    pr_manager.add_labels = AsyncMock()
    pr_manager._run_gh = AsyncMock(return_value='{"labels":[],"body":""}')
    pr_manager._repo = "owner/repo"

    loop = ReportIssueLoop(
        config=deps.config,
        state=state,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
        runner=MagicMock(),
    )
    return loop, state


class TestCrashVsNoIssueDistinguishable:
    """The return value of _do_work must distinguish crashes from no-issue runs."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6408 — fix not yet landed", strict=False)
    async def test_agent_crash_result_differs_from_no_issue_result(
        self, tmp_path: Path
    ) -> None:
        """Crash and no-issue paths must produce distinguishable return dicts.

        Current buggy code returns identical dicts for both — this test is RED.
        """
        loop, state = _make_loop(tmp_path)

        # --- Path A: agent runs successfully but finds no issue URL ---
        report_a = PendingReport(description="No issue produced")
        state.enqueue_report(report_a)
        state.track_report(report_a)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "Agent finished — nothing to report."
            result_no_issue = await loop._do_work()

        # --- Path B: agent crashes with an exception ---
        report_b = PendingReport(description="Agent will crash")
        state.enqueue_report(report_b)
        state.track_report(report_b)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = RuntimeError("unexpected crash in agent")
            result_crash = await loop._do_work()

        # Both should be non-None (they are failure results)
        assert result_no_issue is not None, "no-issue path should return a result dict"
        assert result_crash is not None, "crash path should return a result dict"

        # The core assertion: the two results MUST be distinguishable.
        # After the fix, the crash result should carry a signal like
        # "agent_crashed": True or a different "error" value.
        assert result_crash != result_no_issue, (
            "Bug #6408: crash and no-issue return dicts are identical — "
            "caller cannot distinguish agent crash from genuine no-issue result. "
            f"crash={result_crash!r}, no_issue={result_no_issue!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6408 — fix not yet landed", strict=False)
    async def test_agent_crash_signals_crash_in_result(self, tmp_path: Path) -> None:
        """When the agent crashes, the result dict must include a crash indicator.

        Current buggy code has no such indicator — this test is RED.
        """
        loop, state = _make_loop(tmp_path)
        report = PendingReport(description="Agent will crash")
        state.enqueue_report(report)
        state.track_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.side_effect = ValueError("boom")
            result = await loop._do_work()

        assert result is not None
        # The result must explicitly signal that an agent crash occurred,
        # e.g. via an "agent_crashed" key or similar.  The exact key name
        # is up to the fix, but SOME crash indicator must be present.
        has_crash_signal = (
            result.get("agent_crashed") is True
            or result.get("error") == "agent_crashed"
            or "crash" in str(result.get("error", "")).lower()
        )
        assert has_crash_signal, (
            "Bug #6408: result dict has no crash indicator after agent exception. "
            f"result={result!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6408 — fix not yet landed", strict=False)
    async def test_no_issue_result_does_not_signal_crash(self, tmp_path: Path) -> None:
        """A clean no-issue run must NOT have a crash indicator.

        This guards against a naive fix that always sets the flag.
        """
        loop, state = _make_loop(tmp_path)
        report = PendingReport(description="Agent produces no issue")
        state.enqueue_report(report)
        state.track_report(report)

        with patch(
            "report_issue_loop.stream_claude_process", new_callable=AsyncMock
        ) as mock_stream:
            mock_stream.return_value = "All clear, nothing to file."
            result = await loop._do_work()

        assert result is not None
        assert result.get("agent_crashed") is not True, (
            "Clean no-issue run should not have agent_crashed flag"
        )

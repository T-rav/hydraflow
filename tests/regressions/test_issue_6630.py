"""Regression test for issue #6630.

Bug 1 (medium): ``CIMonitorLoop._do_work`` catches ``except Exception`` on
``get_latest_ci_status()`` (line 67), so an ``AuthenticationError`` (expired
GitHub token) is logged as a transient warning and suppressed.  The loop keeps
running without CI data, silently producing stale status.  The base class
``_execute_cycle`` already re-raises ``AuthenticationError``, but the inner
catch in ``_do_work`` prevents the exception from ever reaching there.

Bug 2 (low): ``_update_decision`` in ``health_monitor_loop.py`` uses
``contextlib.suppress(OSError)`` for tmpfile cleanup — a non-OSError from
``os.unlink`` would propagate and mask the original exception.

These tests will FAIL (RED) against the current code because ``_do_work``
does not distinguish ``AuthenticationError`` from transient failures.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ci_monitor_loop import CIMonitorLoop
from health_monitor_loop import _update_decision
from subprocess_util import AuthenticationError
from tests.helpers import make_bg_loop_deps


def _make_ci_loop(
    tmp_path: Path,
) -> tuple[CIMonitorLoop, MagicMock]:
    """Build a CIMonitorLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)
    pr_manager = MagicMock()
    pr_manager.get_latest_ci_status = AsyncMock(return_value=("success", ""))
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])
    pr_manager.create_issue = AsyncMock(return_value=999)
    pr_manager.close_issue = AsyncMock()
    pr_manager.post_comment = AsyncMock()

    loop = CIMonitorLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, pr_manager


class TestIssue6630AuthenticationErrorNotSuppressed:
    """AuthenticationError from get_latest_ci_status must propagate, not be
    swallowed by the broad ``except Exception`` at ci_monitor_loop.py:67."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6630 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates_from_do_work(
        self, tmp_path: Path
    ) -> None:
        """An expired GitHub token should crash the CI monitor loop so the
        orchestrator can handle it — not be silently suppressed.

        Currently FAILS because line 67 catches all ``Exception`` subclasses,
        so ``AuthenticationError`` is swallowed and ``{"error": True}`` is
        returned instead of propagating.
        """
        loop, pr = _make_ci_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = AuthenticationError(
            "Bad credentials — GitHub token expired"
        )

        # After the fix, AuthenticationError should propagate.
        # Current code catches it and returns {"error": True}.
        with pytest.raises(AuthenticationError, match="token expired"):
            await loop._do_work()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6630 — fix not yet landed", strict=False)
    async def test_authentication_error_not_logged_as_transient(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError should NOT be logged at WARNING level as though
        it were a transient network glitch.

        Currently FAILS because the except block at line 68 logs
        "could not fetch CI status" at WARNING and returns normally.
        """
        loop, pr = _make_ci_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = AuthenticationError("Bad credentials")

        # The method should raise, not return a result.
        result = await loop._do_work()
        # If we get here, the bug is present: AuthenticationError was swallowed.
        assert result is None or result.get("error") is not True, (
            "AuthenticationError was caught and treated as a transient error "
            "instead of propagating — CI monitor will run forever with stale data"
        )

    @pytest.mark.asyncio
    async def test_transient_errors_still_caught(self, tmp_path: Path) -> None:
        """Ordinary transient errors (RuntimeError, OSError) should still be
        caught and not crash the loop.

        This test should PASS both before and after the fix.
        """
        loop, pr = _make_ci_loop(tmp_path)
        pr.get_latest_ci_status.side_effect = RuntimeError("API timeout")

        result = await loop._do_work()
        assert result is not None
        assert result.get("error") is True


class TestIssue6630DecisionFileCleanup:
    """_update_decision tmpfile cleanup uses ``contextlib.suppress(OSError)``
    — a non-OSError from os.unlink would propagate and mask the original."""

    @pytest.mark.xfail(reason="Regression for issue #6630 — fix not yet landed", strict=False)
    def test_cleanup_suppresses_all_exceptions_on_unlink(self, tmp_path: Path) -> None:
        """If os.unlink raises a non-OSError in the cleanup path, the original
        exception should still be the one raised — not the cleanup error.

        Currently FAILS because ``contextlib.suppress(OSError)`` does not
        suppress non-OSError exceptions from os.unlink.
        """
        decisions_dir = tmp_path / "decisions"
        decisions_dir.mkdir()

        # Seed a decision record so _update_decision has something to rewrite
        seed = {"decision_id": "adj-test1234", "parameter": "agent_timeout"}
        decisions_file = decisions_dir / "decisions.jsonl"
        decisions_file.write_text(json.dumps(seed) + "\n", encoding="utf-8")

        original_error = ValueError("disk write failed during test")

        # Patch os.fdopen to raise the original error during the write phase,
        # and os.unlink to raise a non-OSError during cleanup.

        def patched_fdopen(fd: int, *args, **kwargs):  # noqa: ANN002, ANN003
            os.close(fd)
            raise original_error

        with (
            patch("health_monitor_loop.os.fdopen", side_effect=patched_fdopen),
            patch(
                "health_monitor_loop.os.unlink",
                side_effect=RuntimeError("exotic unlink failure"),
            ),
        ):
            # The original ValueError should be raised, not the RuntimeError
            # from cleanup. Currently FAILS because suppress(OSError) doesn't
            # catch RuntimeError, so the cleanup error masks the original.
            with pytest.raises(ValueError, match="disk write failed"):
                _update_decision(
                    decisions_dir,
                    "adj-test1234",
                    {"outcome_verified": "improved"},
                )

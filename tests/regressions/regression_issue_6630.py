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

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ci_monitor_loop import CIMonitorLoop
from file_util import atomic_write
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

        # As written this called `_do_work()` bare and asserted on its return
        # value, so the fixed behaviour — propagating — made the test ERROR
        # rather than pass; only the bug could satisfy it. The docstring's
        # "should NOT be logged as transient" is the contract, and
        # `reraise_on_credit_or_bug` in `_do_work` now delivers it.
        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await loop._do_work()

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
    """Temp-file cleanup must not mask the exception that triggered it.

    The god-class decomposition (Refs #11547) moved ``_update_decision``'s
    write into ``AuditChain.rewrite`` -> ``file_util.atomic_write``, so the
    ``suppress(OSError)`` this issue describes no longer sits in
    ``health_monitor_loop`` — and the original patch target
    (``health_monitor_loop.os``) stopped existing, which is why this pin
    errored with ``AttributeError`` instead of reporting the defect. The
    property is unchanged and the defect was still live; it just moved
    somewhere WIDER, since every atomic write in the codebase shares that
    helper. Driving ``atomic_write`` directly keeps the pin on the code that
    actually implements the behaviour, wherever its callers move to.
    """

    def test_cleanup_suppresses_all_exceptions_on_unlink(self, tmp_path: Path) -> None:
        """If os.unlink raises a non-OSError in the cleanup path, the original
        exception should still be the one raised — not the cleanup error.

        Currently FAILS because ``contextlib.suppress(OSError)`` does not
        suppress non-OSError exceptions from os.unlink.
        """
        target = tmp_path / "decisions" / "decisions.jsonl"
        original_error = ValueError("disk write failed during test")

        # Fail the write, then fail the cleanup with a NON-OSError. The
        # original error must survive; the unlink failure must not replace it.
        def patched_fdopen(fd: int, *args, **kwargs):  # noqa: ANN002, ANN003
            os.close(fd)
            raise original_error

        with (
            patch("file_util.os.fdopen", side_effect=patched_fdopen),
            patch(
                "file_util.os.unlink",
                side_effect=RuntimeError("exotic unlink failure"),
            ),
            pytest.raises(ValueError, match="disk write failed"),
        ):
            atomic_write(target, "body")

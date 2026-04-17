"""Regression test for issue #6768.

Bug: ``PRManager.get_latest_ci_status()`` (line 758) and
``PRManager.list_issues_by_label()`` (line 714) use a broad
``except Exception: logger.warning(...); raise`` pattern.  This means
*every* exception — including ``AuthenticationError`` — is logged as a
warning before being re-raised.

For ``AuthenticationError`` this is actively harmful: the CI monitor loop
calls ``get_latest_ci_status()`` every poll cycle, so every auth failure
generates a misleading "Could not fetch CI status" warning *in addition*
to the real auth-error handling further up the call stack.

Expected behaviour after fix:
  - ``AuthenticationError`` propagates out of these methods **without**
    a spurious ``logger.warning`` call.
  - The bare ``except Exception: …; raise`` wrapper is removed (or
    replaced with specific handling).

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus
from pr_manager import PRManager
from subprocess_util import AuthenticationError
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
# Test 1 — get_latest_ci_status: AuthenticationError must not emit warning
# ---------------------------------------------------------------------------


class TestGetLatestCIStatusNoSpuriousWarning:
    """Issue #6768 — ``get_latest_ci_status`` should let
    ``AuthenticationError`` propagate without logging a warning first.

    Currently FAILS: the ``except Exception`` on line 758 logs a warning
    for *every* exception type before re-raising.
    """

    @pytest.mark.asyncio
    async def test_auth_error_propagates_without_warning_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When _run_gh raises AuthenticationError, the method should
        re-raise it WITHOUT emitting a warning log.

        The current code logs ``"Could not fetch CI status"`` at WARNING
        level for all exceptions, including auth errors.  After the fix
        the wrapper is removed so no warning is emitted.
        """
        mgr = _make_pr_manager()
        auth_exc = AuthenticationError("bad credentials")

        with patch.object(mgr, "_run_gh", new_callable=AsyncMock, side_effect=auth_exc):
            with caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"):
                with pytest.raises(AuthenticationError):
                    await mgr.get_latest_ci_status()

        # After the fix, AuthenticationError should propagate cleanly
        # with NO warning log.  The current buggy code emits:
        #   WARNING  hydraflow.pr_manager  Could not fetch CI status
        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and "Could not fetch CI status" in r.message
        ]
        assert warning_messages == [], (
            f"AuthenticationError triggered a spurious warning log: "
            f"{warning_messages!r} — the 'except Exception: "
            f"logger.warning(...); raise' wrapper on line 758 should be "
            f"removed so auth errors propagate cleanly"
        )


# ---------------------------------------------------------------------------
# Test 2 — list_issues_by_label: AuthenticationError must not emit warning
# ---------------------------------------------------------------------------


class TestListIssuesByLabelNoSpuriousWarning:
    """Issue #6768 — ``list_issues_by_label`` should let
    ``AuthenticationError`` propagate without logging a warning first.

    Currently FAILS: the ``except Exception`` on line 714 logs a warning
    for every exception type before re-raising.
    """

    @pytest.mark.asyncio
    async def test_auth_error_propagates_without_warning_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When _run_gh raises AuthenticationError inside
        list_issues_by_label, no warning should be logged.

        The current code logs ``"Failed to list issues for label ..."``
        at WARNING level for all exceptions.  After the fix, the wrapper
        is removed.
        """
        mgr = _make_pr_manager()
        auth_exc = AuthenticationError("bad credentials")

        with patch.object(mgr, "_run_gh", new_callable=AsyncMock, side_effect=auth_exc):
            with caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"):
                with pytest.raises(AuthenticationError):
                    await mgr.list_issues_by_label("hydraflow-ready")

        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and "Failed to list issues" in r.message
        ]
        assert warning_messages == [], (
            f"AuthenticationError triggered a spurious warning log: "
            f"{warning_messages!r} — the 'except Exception: "
            f"logger.warning(...); raise' wrapper on line 714 should be "
            f"removed so auth errors propagate cleanly"
        )


# ---------------------------------------------------------------------------
# Test 3 — get_latest_ci_status: generic RuntimeError also should not warn
# ---------------------------------------------------------------------------


class TestGetLatestCIStatusGenericExceptionNoWarning:
    """The except-and-reraise wrapper adds no handling value for ANY
    exception type — it only adds log noise.  After the fix, even a
    generic RuntimeError should propagate without a warning log.
    """

    @pytest.mark.asyncio
    async def test_runtime_error_propagates_without_warning_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mgr = _make_pr_manager()

        with (
            patch.object(
                mgr,
                "_run_gh",
                new_callable=AsyncMock,
                side_effect=RuntimeError("gh CLI failed"),
            ),
            caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
        ):
            with pytest.raises(RuntimeError):
                await mgr.get_latest_ci_status()

        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and "Could not fetch CI status" in r.message
        ]
        assert warning_messages == [], (
            f"RuntimeError triggered a spurious warning log: "
            f"{warning_messages!r} — the catch-and-reraise wrapper adds "
            f"no value and should be removed"
        )

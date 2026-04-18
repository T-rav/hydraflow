"""Regression test for issue #6417.

Bug: ``PRManager.list_issues_by_label`` (line 714) and
``get_latest_ci_status`` (line 758) use a catch-log-rethrow pattern::

    except Exception:
        logger.warning(..., exc_info=True)
        raise

Callers (``stale_issue_gc_loop``, ``ci_monitor_loop``, ``diagnostic_loop``)
also catch the re-raised exception and log at WARNING level.  This produces
**duplicate** WARNING-level log entries for a single error, making it harder
to diagnose failures and inflating log noise.

Expected behaviour after fix:
  - Each exception produces exactly ONE warning-level log entry (at the
    caller, where the error is actually handled).
  - ``PRManager`` methods let exceptions propagate without logging, OR
    log at DEBUG level at most.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager():
    """Build a PRManager with the minimum config needed for the methods under test."""
    from config import HydraFlowConfig
    from events import EventBus
    from pr_manager import PRManager

    config = MagicMock(spec=HydraFlowConfig)
    config.repo = "test-org/test-repo"
    config.main_branch = "main"
    config.gh_max_retries = 0
    config.dry_run = False
    config.repo_root = Path("/tmp/fake-repo")

    bus = MagicMock(spec=EventBus)
    return PRManager(config, bus)


PR_MANAGER_LOGGER = "hydraflow.pr_manager"


# ---------------------------------------------------------------------------
# Tests for list_issues_by_label
# ---------------------------------------------------------------------------


class TestListIssuesByLabelNoDuplicateWarnings:
    """Issue #6417 — list_issues_by_label must not log at WARNING level.

    The caller is responsible for logging; the inner method should not
    produce its own WARNING entry that duplicates the caller's.
    """

    @pytest.mark.asyncio
    async def test_no_warning_log_from_list_issues_by_label(self, caplog) -> None:
        """When _run_gh raises, list_issues_by_label must not emit a WARNING.

        Current code: ``except Exception: logger.warning(...); raise``
        → produces a WARNING log here AND at the caller → duplicate.

        After fix: no try/except (or at most logger.debug), so
        the only WARNING comes from the caller.
        """
        mgr = _make_pr_manager()
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("gh CLI failed"))

        with caplog.at_level(logging.DEBUG, logger=PR_MANAGER_LOGGER):
            with pytest.raises(RuntimeError, match="gh CLI failed"):
                await mgr.list_issues_by_label("hydraflow-ready")

        # Collect WARNING-level records from the pr_manager logger
        pr_manager_warnings = [
            r
            for r in caplog.records
            if r.name == PR_MANAGER_LOGGER and r.levelno == logging.WARNING
        ]
        assert pr_manager_warnings == [], (
            f"list_issues_by_label emitted {len(pr_manager_warnings)} WARNING log(s) "
            f"before re-raising the exception. This is the catch-log-rethrow "
            f"anti-pattern from issue #6417 — callers will log again, causing "
            f"duplicate entries. Messages: "
            f"{[r.message for r in pr_manager_warnings]}"
        )

    @pytest.mark.asyncio
    async def test_exception_still_propagates(self) -> None:
        """Exceptions from _run_gh must still propagate to the caller.

        This test should be GREEN on current code — it documents the
        propagation contract that must be preserved by the fix.
        """
        mgr = _make_pr_manager()
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("gh CLI failed"))

        with pytest.raises(RuntimeError, match="gh CLI failed"):
            await mgr.list_issues_by_label("hydraflow-ready")


# ---------------------------------------------------------------------------
# Tests for get_latest_ci_status
# ---------------------------------------------------------------------------


class TestGetLatestCiStatusNoDuplicateWarnings:
    """Issue #6417 — get_latest_ci_status must not log at WARNING level.

    Same anti-pattern: catch-log(WARNING)-rethrow, caller logs again.
    """

    @pytest.mark.asyncio
    async def test_no_warning_log_from_get_latest_ci_status(self, caplog) -> None:
        """When _run_gh raises, get_latest_ci_status must not emit a WARNING.

        Current code: ``except Exception: logger.warning(...); raise``
        → duplicate WARNING at caller.
        """
        mgr = _make_pr_manager()
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("gh CLI failed"))

        with caplog.at_level(logging.DEBUG, logger=PR_MANAGER_LOGGER):
            with pytest.raises(RuntimeError, match="gh CLI failed"):
                await mgr.get_latest_ci_status()

        pr_manager_warnings = [
            r
            for r in caplog.records
            if r.name == PR_MANAGER_LOGGER and r.levelno == logging.WARNING
        ]
        assert pr_manager_warnings == [], (
            f"get_latest_ci_status emitted {len(pr_manager_warnings)} WARNING log(s) "
            f"before re-raising the exception. This is the catch-log-rethrow "
            f"anti-pattern from issue #6417 — callers will log again, causing "
            f"duplicate entries. Messages: "
            f"{[r.message for r in pr_manager_warnings]}"
        )

    @pytest.mark.asyncio
    async def test_exception_still_propagates(self) -> None:
        """Exceptions from _run_gh must still propagate to the caller.

        GREEN on current code — documents the contract.
        """
        mgr = _make_pr_manager()
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("gh CLI failed"))

        with pytest.raises(RuntimeError, match="gh CLI failed"):
            await mgr.get_latest_ci_status()

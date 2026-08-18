"""Regression test for issue #6460.

StaleIssueLoop._do_work (line 68, 132) and StaleIssueGCLoop._do_work
(line 63, 106) both use ``except Exception:`` for GitHub API calls.
Because AuthenticationError and CreditExhaustedError are subclasses of
RuntimeError (which is a subclass of Exception), they get swallowed
inside _do_work and never propagate to BaseBackgroundLoop._execute_cycle,
which is the layer that re-raises them as fatal errors.

The tests below verify that these fatal errors escape _do_work so the
loop supervisor can shut down or pause the loop.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from stale_issue_gc_loop import StaleIssueGCLoop
from stale_issue_loop import StaleIssueLoop
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# StaleIssueLoop helpers
# ---------------------------------------------------------------------------


def _make_stale_loop(
    tmp_path: Path,
) -> tuple[StaleIssueLoop, asyncio.Event, MagicMock, MagicMock]:
    """Build a StaleIssueLoop with test-friendly mocks."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    pr_manager = MagicMock()
    # Default: return empty issue list
    pr_manager.list_all_issues = AsyncMock(return_value=[])
    pr_manager.post_comment = AsyncMock()
    pr_manager.close_issue = AsyncMock()
    pr_manager.list_branch_refs = AsyncMock(return_value=[])
    pr_manager.list_branch_commits = AsyncMock(return_value=[])

    state = MagicMock()
    state.get_stale_issue_settings.return_value = MagicMock(
        staleness_days=30,
        excluded_labels=[],
        dry_run=False,
    )
    state.get_stale_issue_closed.return_value = set()
    state.add_stale_issue_closed = MagicMock()

    loop = StaleIssueLoop(
        config=deps.config,
        prs=pr_manager,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager, state


def _stale_issue_list(number: int = 42, days_old: int = 60) -> list[dict]:
    """Return a list_all_issues-shaped list with one stale issue."""
    updated = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
    return [
        {
            "number": number,
            "title": f"Stale issue #{number}",
            "updatedAt": updated,
            "labels": [],
        }
    ]


# ---------------------------------------------------------------------------
# StaleIssueGCLoop helpers
# ---------------------------------------------------------------------------


def _make_gc_loop(
    tmp_path: Path,
) -> tuple[StaleIssueGCLoop, asyncio.Event, MagicMock]:
    """Build a StaleIssueGCLoop with test-friendly mocks."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    pr_manager = MagicMock()
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])
    pr_manager.get_issue_updated_at = AsyncMock(return_value=None)
    pr_manager.post_comment = AsyncMock()
    pr_manager.close_issue = AsyncMock()
    pr_manager.list_open_issue_numbers = AsyncMock(return_value=[])

    loop = StaleIssueGCLoop(
        config=deps.config,
        pr_manager=pr_manager,
        state=MagicMock(),
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, pr_manager


# ===========================================================================
# StaleIssueLoop — AuthenticationError
# ===========================================================================


class TestStaleIssueLoopAuthError:
    """AuthenticationError must escape StaleIssueLoop._do_work."""

    @pytest.mark.asyncio
    async def test_auth_error_on_issue_fetch_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from list_all_issues (issue list) must not be caught."""
        loop, _stop, pr, _state = _make_stale_loop(tmp_path)
        pr.list_all_issues.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_auth_error_on_issue_close_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from post_comment (per-issue close) must not be caught."""
        loop, _stop, pr, _state = _make_stale_loop(tmp_path)
        pr.list_all_issues.return_value = _stale_issue_list()
        pr.post_comment.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()


# ===========================================================================
# StaleIssueLoop — CreditExhaustedError
# ===========================================================================


class TestStaleIssueLoopCreditExhausted:
    """CreditExhaustedError must escape StaleIssueLoop._do_work."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_issue_fetch_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from list_all_issues (issue list) must not be caught."""
        loop, _stop, pr, _state = _make_stale_loop(tmp_path)
        pr.list_all_issues.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_issue_close_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from post_comment (per-issue close) must not be caught."""
        loop, _stop, pr, _state = _make_stale_loop(tmp_path)
        pr.list_all_issues.return_value = _stale_issue_list()
        pr.post_comment.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


# ===========================================================================
# StaleIssueGCLoop — AuthenticationError
# ===========================================================================


class TestStaleIssueGCLoopAuthError:
    """AuthenticationError must escape StaleIssueGCLoop._do_work."""

    @pytest.mark.asyncio
    async def test_auth_error_on_list_issues_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError from list_issues_by_label must not be caught."""
        loop, _stop, pr = _make_gc_loop(tmp_path)
        pr.list_issues_by_label.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_auth_error_on_per_issue_processing_propagates(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from get_issue_updated_at must not be caught."""
        loop, _stop, pr = _make_gc_loop(tmp_path)
        pr.list_issues_by_label.return_value = [{"number": 99}]
        pr.get_issue_updated_at.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(AuthenticationError):
            await loop._do_work()


# ===========================================================================
# StaleIssueGCLoop — CreditExhaustedError
# ===========================================================================


class TestStaleIssueGCLoopCreditExhausted:
    """CreditExhaustedError must escape StaleIssueGCLoop._do_work."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_list_issues_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from list_issues_by_label must not be caught."""
        loop, _stop, pr = _make_gc_loop(tmp_path)
        pr.list_issues_by_label.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_on_per_issue_processing_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from get_issue_updated_at must not be caught."""
        loop, _stop, pr = _make_gc_loop(tmp_path)
        pr.list_issues_by_label.return_value = [{"number": 99}]
        pr.get_issue_updated_at.side_effect = CreditExhaustedError("Credits exhausted")

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


# ===========================================================================
# Transient errors still caught (guard against over-fixing)
# ===========================================================================


class TestTransientErrorsStillCaught:
    """Transient RuntimeError should still be caught — this is correct behavior
    that must be preserved after the fix."""

    @pytest.mark.asyncio
    async def test_stale_loop_transient_error_on_fetch_is_caught(
        self, tmp_path: Path
    ) -> None:
        """Transient RuntimeError on issue fetch is handled gracefully."""
        loop, _stop, pr, _state = _make_stale_loop(tmp_path)
        pr.list_all_issues.side_effect = RuntimeError("API timeout")

        # Should NOT raise
        result = await loop._do_work()
        assert result is not None

    @pytest.mark.asyncio
    async def test_gc_loop_transient_error_on_list_is_caught(
        self, tmp_path: Path
    ) -> None:
        """Transient RuntimeError on list_issues_by_label is handled gracefully."""
        loop, _stop, pr = _make_gc_loop(tmp_path)
        pr.list_issues_by_label.side_effect = RuntimeError("API timeout")

        # Should NOT raise
        result = await loop._do_work()
        assert result is not None

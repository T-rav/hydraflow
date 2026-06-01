"""Regression test for issue #6862.

Bug: DependabotMergeLoop._do_work iterates bot_prs with no per-PR
try/except. A transient RuntimeError on any one PR aborts the entire
for-loop, leaving subsequent PRs unprocessed for that cycle.

Expected behaviour after fix:
  - A transient RuntimeError on one PR is caught, logged, and the loop
    continues to process remaining PRs.
  - AuthenticationError / CreditExhaustedError still propagate (not
    caught by per-PR handler).

These tests assert the *correct* behaviour, so they are RED against
the current (buggy) code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dependabot_merge_loop import DependabotMergeLoop
from models import DependabotMergeSettings, PRListItem
from tests.helpers import make_bg_loop_deps


def _make_pr(
    pr: int, author: str = "dependabot[bot]", title: str = "Bump foo"
) -> PRListItem:
    return PRListItem(
        pr=pr,
        author=author,
        title=title,
        url=f"https://github.com/o/r/pull/{pr}",
    )


_FailureStrategy = Literal["skip", "hitl", "close"]


def _make_state(
    *,
    authors: list[str] | None = None,
    failure_strategy: _FailureStrategy = "skip",
    processed: set[int] | None = None,
) -> MagicMock:
    state = MagicMock()
    settings = DependabotMergeSettings(
        authors=authors or ["dependabot[bot]"],
        failure_strategy=failure_strategy,
    )
    state.get_dependabot_merge_settings.return_value = settings
    state.get_dependabot_merge_processed.return_value = processed or set()
    return state


def _make_loop(
    tmp_path: Path,
    *,
    open_prs: list[PRListItem] | None = None,
    prs_mock: MagicMock | None = None,
    failure_strategy: _FailureStrategy = "skip",
) -> tuple[DependabotMergeLoop, MagicMock, MagicMock]:
    """Build a DependabotMergeLoop with injectable prs mock.

    Returns (loop, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True, dependabot_merge_interval=60)

    cache = MagicMock()
    cache.get_open_prs.return_value = open_prs or []

    if prs_mock is None:
        prs_mock = MagicMock()
        prs_mock.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs_mock.submit_review = AsyncMock(return_value=True)
        prs_mock.merge_pr = AsyncMock(return_value=True)
        prs_mock.add_labels = AsyncMock()
        prs_mock.post_comment = AsyncMock()
        prs_mock.close_issue = AsyncMock()

    state = _make_state(failure_strategy=failure_strategy)

    loop = DependabotMergeLoop(
        config=deps.config,
        cache=cache,
        prs=prs_mock,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs_mock, state


class TestIssue6862TransientErrorDoesNotAbortBatch:
    """A transient RuntimeError on one PR must not abort the remaining PRs."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6862 — fix not yet landed", strict=False)
    async def test_runtime_error_on_first_pr_still_processes_remaining(
        self, tmp_path: Path
    ) -> None:
        """If wait_for_ci raises RuntimeError on PR #1, PRs #2 and #3 should
        still be processed and merged."""
        pr1, pr2, pr3 = _make_pr(1), _make_pr(2), _make_pr(3)

        prs = MagicMock()
        # PR #1 raises a transient error; PRs #2 and #3 succeed
        prs.wait_for_ci = AsyncMock(
            side_effect=[
                RuntimeError("502 Server Error"),
                (True, "All checks passed"),
                (True, "All checks passed"),
            ]
        )
        prs.submit_review = AsyncMock(return_value=True)
        prs.merge_pr = AsyncMock(return_value=True)
        prs.add_labels = AsyncMock()
        prs.post_comment = AsyncMock()
        prs.close_issue = AsyncMock()

        loop, _, state = _make_loop(tmp_path, open_prs=[pr1, pr2, pr3], prs_mock=prs)

        result = await loop._do_work()

        # After fix: PRs #2 and #3 should have been merged despite PR #1 failing.
        # Current buggy code raises the RuntimeError, so _do_work never returns
        # a result dict — this assertion will fail.
        assert result is not None, "_do_work raised instead of returning a result dict"
        assert result["merged"] == 2, (
            f"Expected 2 merged PRs (PR #2 and #3), got {result['merged']}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6862 — fix not yet landed", strict=False)
    async def test_runtime_error_on_merge_still_processes_remaining(
        self, tmp_path: Path
    ) -> None:
        """If merge_pr raises RuntimeError on PR #1, PRs #2 and #3 should
        still be processed."""
        pr1, pr2, pr3 = _make_pr(1), _make_pr(2), _make_pr(3)

        prs = MagicMock()
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.submit_review = AsyncMock(return_value=True)
        # PR #1 merge raises; PRs #2 and #3 succeed
        prs.merge_pr = AsyncMock(
            side_effect=[
                RuntimeError("422 Unprocessable Entity"),
                True,
                True,
            ]
        )
        prs.add_labels = AsyncMock()
        prs.post_comment = AsyncMock()
        prs.close_issue = AsyncMock()

        loop, _, state = _make_loop(tmp_path, open_prs=[pr1, pr2, pr3], prs_mock=prs)

        result = await loop._do_work()

        assert result is not None, "_do_work raised instead of returning a result dict"
        assert result["merged"] == 2, (
            f"Expected 2 merged PRs (PR #2 and #3), got {result['merged']}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6862 — fix not yet landed", strict=False)
    async def test_runtime_error_on_hitl_escalation_still_processes_remaining(
        self, tmp_path: Path
    ) -> None:
        """If add_labels raises RuntimeError during HITL escalation on PR #1,
        PRs #2 and #3 should still be processed."""
        pr1, pr2, pr3 = _make_pr(1), _make_pr(2), _make_pr(3)

        prs = MagicMock()
        # All PRs fail CI so all go to HITL path
        prs.wait_for_ci = AsyncMock(
            return_value=(False, "2/5 checks failed: lint, test")
        )
        prs.submit_review = AsyncMock(return_value=True)
        prs.merge_pr = AsyncMock(return_value=True)
        # PR #1 add_labels raises; PRs #2 and #3 succeed
        prs.add_labels = AsyncMock(
            side_effect=[
                RuntimeError("502 Server Error"),
                None,
                None,
            ]
        )
        prs.post_comment = AsyncMock()
        prs.close_issue = AsyncMock()

        loop, _, state = _make_loop(
            tmp_path,
            open_prs=[pr1, pr2, pr3],
            prs_mock=prs,
            failure_strategy="hitl",
        )

        result = await loop._do_work()

        assert result is not None, "_do_work raised instead of returning a result dict"
        # PR #1 errored, PRs #2 and #3 should have been escalated
        assert result["failed"] >= 2, (
            f"Expected at least 2 failed PRs (#2 and #3 escalated), got {result['failed']}"
        )

"""Item 2 (#9889): DIRTY content-conflict auto-heal for bot/factory PRs.

Before this fix, a CI-green bot PR whose merge failed on a genuine content
conflict hit ``merge_pr`` → False and the loop just logged and gave up — the
arch self-heal only fires on arch-staleness CI text, never on mergeable-state
conflicts — so conflicting factory PRs sat DIRTY forever. Pinned contracts:

1. Close-supersede: a conflicting factory-maintenance PR (ul-*/pricing/wiki)
   is closed with an explanatory comment — its loop regenerates a fresh PR
   (single-flight #9939), so rebasing generated content is wasted work.
2. Human PRs stay untouched: a conflicting shepherd-prefix (fix/ etc.) PR is
   never closed, never update-branched, never marked processed — one
   DedupStore-bounded comment tells the author, and that is all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_dependabot_merge_loop import _make_loop, _make_pr


@pytest.mark.asyncio
async def test_conflicting_factory_maintenance_pr_is_closed_superseded(
    tmp_path: Path,
) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9889, author="HydraOps-T-rav", branch="ul-proposer/abc123")],
        merge_result=False,
        mergeable=False,  # GitHub: CONFLICTING
    )

    result = await loop._do_work()

    # Close-supersede, not log-and-give-up: comment + close_pr + processed.
    prs.post_comment.assert_awaited_once()
    assert "conflict" in prs.post_comment.await_args.args[1].lower()
    prs.close_pr.assert_awaited_once_with(9889)
    state.add_dependabot_merge_processed.assert_called_once_with(9889)
    # Never a rebase of generated content, never the issue-close surface.
    prs.update_pr_branch.assert_not_awaited()
    prs.close_issue.assert_not_awaited()
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_conflicting_human_pr_is_never_closed_or_update_branched(
    tmp_path: Path,
) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9890, author="T-rav", branch="fix/human-owned")],
        merge_result=False,
        mergeable=False,
    )

    with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock(return_value=[])):
        await loop._do_work()
        await loop._do_work()  # still open + conflicting next cycle

    # One comment ever (DedupStore), and the PR remains fully the author's:
    prs.post_comment.assert_awaited_once()
    prs.close_pr.assert_not_awaited()
    prs.close_issue.assert_not_awaited()
    prs.update_pr_branch.assert_not_awaited()
    state.add_dependabot_merge_processed.assert_not_called()

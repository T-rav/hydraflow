"""Regression #10526: dependabot_merge must not abort on SelfReviewError.

`DependabotMergeLoop._do_work` approves a green bot PR before merging it. But
the bot cannot approve its OWN PR (GitHub blocks self-review with
``SelfReviewError``), and the base branch requires 0 approving reviews anyway.
Before the fix, that error propagated out of ``_do_work`` and failed the whole
loop iteration — so ``merge_pr`` was never reached and every bot caretaker PR
(wiki maintenance / UL term-proposer / pricing refresh) piled up unmerged while
the loop errored each cycle. The self-approval is now best-effort.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from comment_formatter import SelfReviewError
from tests.test_dependabot_merge_loop import _make_loop, _make_pr


@pytest.mark.asyncio
async def test_self_review_error_does_not_block_merge(tmp_path: Path) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(10)],
        ci_result=(True, "All checks passed"),
    )
    # The bot cannot approve its own PR — submit_review raises SelfReviewError.
    prs.submit_review = AsyncMock(
        side_effect=SelfReviewError("cannot approve own pull request")
    )

    result = await loop._do_work()
    assert result is not None

    # The self-approval failed, but the merge must still go through.
    prs.merge_pr.assert_awaited_once_with(10, auto_rebase=True)
    assert result["merged"] == 1
    state.add_dependabot_merge_processed.assert_called_once_with(10)

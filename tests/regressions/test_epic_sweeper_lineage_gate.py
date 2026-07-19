"""Regression (#9757): the epic sweeper must not treat a decomposed-closed child
as resolved until its replacement epic closes.

A child C of epic E1 is closed the moment it is decomposed into a replacement
epic E2, but C's work lives on under E2. If the sweeper counted C as resolved
while E2 (and its grandchildren) were still open, E1 would auto-close
prematurely. The gate holds E1 open until E2's GitHub issue is closed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epic_sweeper_loop import EpicSweeperLoop
from models import EpicState
from tests.conftest import IssueFactory
from tests.helpers import make_bg_loop_deps

_EPIC_BODY = "## Sub-issues\n\n- [ ] #3\n- [ ] #4\n"
# #3 was decomposed into replacement epic E2 (#5).
_CHILD = 3
_REPLACEMENT_EPIC = 5


def _issue(n: int, state: str):
    return IssueFactory.create(
        number=n, title=f"Issue #{n}", body="", labels=[], state=state
    )


def _make_loop(tmp_path: Path, *, replacement_open: bool):
    deps = make_bg_loop_deps(tmp_path)

    def _fetch(n: int):
        # Sub-issues #3/#4 are closed; the replacement epic #5 is open or closed
        # per the scenario.
        state_str = (
            "open" if (n == _REPLACEMENT_EPIC and replacement_open) else "closed"
        )
        return _issue(n, state_str)

    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(side_effect=_fetch)
    prs = MagicMock()
    prs.update_issue_body = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    state = MagicMock()
    state.get_replacement_epic = MagicMock(
        side_effect=lambda n: EpicState(
            epic_number=_REPLACEMENT_EPIC, superseded_issue=_CHILD
        )
        if n == _CHILD
        else None
    )
    loop = EpicSweeperLoop(
        config=deps.config, fetcher=fetcher, prs=prs, state=state, deps=deps.loop_deps
    )
    return loop, prs


@pytest.mark.asyncio
async def test_not_swept_while_replacement_epic_open(tmp_path: Path):
    loop, prs = _make_loop(tmp_path, replacement_open=True)
    swept = await loop._try_sweep_epic(2, _EPIC_BODY, [3, 4])
    assert swept is False
    prs.close_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_swept_once_replacement_epic_closed(tmp_path: Path):
    loop, prs = _make_loop(tmp_path, replacement_open=False)
    swept = await loop._try_sweep_epic(2, _EPIC_BODY, [3, 4])
    assert swept is True
    prs.close_issue.assert_awaited()

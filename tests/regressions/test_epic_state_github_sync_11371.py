"""Regression pins for #11371: no zombie stale-epic alerts.

Live symptom (2026-08-16): epic #10914 was closed on GitHub, but its
``epic_states`` entry still read ``closed: false``. ``check_stale_epics``
trusted only local state, so the "Epic #10914 is stale" SYSTEM_ALERT
re-emitted every 30-minute cycle forever and the console banner
resurrected after every dismiss.

Pins:
1. GitHub-closed + locally-open → NO alert, and the local flag heals.
2. Genuinely open + stale → still alerts (the feature is intact).
3. Unreadable GitHub state → fail-soft to alerting (never silently
   suppress a real stale epic).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from epic import EpicManager
from models import EpicState


def _stale_epic(number: int) -> EpicState:
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    return EpicState(
        epic_number=number,
        title=f"Epic {number}",
        child_issues=[],
        created_at=old,
        last_activity=old,
        closed=False,
    )


def _manager(*, issue_state: str | Exception, epic_number: int = 10914):
    mgr = object.__new__(EpicManager)
    mgr._config = SimpleNamespace(epic_stale_days=7)
    epic = _stale_epic(epic_number)
    closed: list[int] = []
    mgr._state = SimpleNamespace(
        get_all_epic_states=lambda: {str(epic_number): epic},
        close_epic=lambda n: closed.append(n),
    )
    get_state = (
        AsyncMock(side_effect=issue_state)
        if isinstance(issue_state, Exception)
        else AsyncMock(return_value=issue_state)
    )
    mgr._prs = SimpleNamespace(get_issue_state=get_state, post_comment=AsyncMock())
    mgr._bus = SimpleNamespace(publish=AsyncMock())
    mgr._is_stale = lambda _e: True
    return mgr, closed


@pytest.mark.asyncio
async def test_github_closed_epic_heals_instead_of_alerting() -> None:
    mgr, closed = _manager(issue_state="CLOSED")
    stale = await mgr.check_stale_epics()
    assert stale == []
    assert closed == [10914]
    mgr._bus.publish.assert_not_awaited()
    mgr._prs.post_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_stale_epic_still_alerts() -> None:
    mgr, closed = _manager(issue_state="OPEN")
    stale = await mgr.check_stale_epics()
    assert stale == [10914]
    assert closed == []
    mgr._bus.publish.assert_awaited()


@pytest.mark.asyncio
async def test_unreadable_state_fails_soft_to_alerting() -> None:
    mgr, closed = _manager(issue_state=RuntimeError("gh down"))
    stale = await mgr.check_stale_epics()
    assert stale == [10914]
    assert closed == []

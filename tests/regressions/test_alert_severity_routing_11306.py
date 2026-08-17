"""Regression pins for #11306: advisory alerts route to the bell.

The console banner is the highest-urgency surface (credit pauses, faults,
HITL). Informational caretaker notices rendered there with identical
weight — operator-reported twice, and the stale-epic notice in particular
resurrected after every dismiss (root cause #11371).

Backend half of the fix: an advisory emitter must mark its payload
``severity="warning"`` so the console routes it to the notice bell. The
frontend half (reducer routing + the bell component) is covered by the
vitest suites; the load-bearing rule there is that UNCLASSIFIED alerts
still default to the banner — a new kind must be demoted deliberately.
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


@pytest.mark.asyncio
async def test_stale_epic_alert_is_advisory_severity() -> None:
    mgr = object.__new__(EpicManager)
    mgr._config = SimpleNamespace(epic_stale_days=7)
    mgr._state = SimpleNamespace(
        get_all_epic_states=lambda: {"10914": _stale_epic(10914)}
    )
    mgr._prs = SimpleNamespace(post_comment=AsyncMock())
    mgr._bus = SimpleNamespace(publish=AsyncMock())
    mgr._is_stale = lambda _e: True

    await mgr.check_stale_epics()

    payload = mgr._bus.publish.await_args_list[0].args[0].data
    assert payload["severity"] == "warning", (
        "a stale-epic notice is information, not a banner emergency — "
        "without severity='warning' the console renders it as a critical "
        "banner that resurrects after every dismiss (#11306)."
    )
    assert payload["source"] == "epic_monitor"

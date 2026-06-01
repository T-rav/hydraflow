"""Regression: MERGE_UPDATE carries the issue number (WS-RT).

The dashboard moves a card review -> merged via the frontend's optimistic
``getPipelineAction``, which returns ``null`` unless ``event.data.issue`` is
present. ``MergeUpdatePayload`` had no ``issue`` field and both publish sites
omitted it, so that move was dead code in production — the card only moved on
the next REST poll, visibly hanging in review. ``merge_pr`` now parses the
issue from the canonical ``Fixes #N:`` title and includes it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from events import EventType
from tests.helpers import ConfigFactory, make_pr_manager


def _make_pr_manager() -> Any:
    config = ConfigFactory.create(repo="owner/repo")
    return make_pr_manager(config=config, event_bus=AsyncMock())


def _merge_update_events(pm: Any) -> list[Any]:
    return [
        call.args[0]
        for call in pm._bus.publish.call_args_list
        if call.args and getattr(call.args[0], "type", None) == EventType.MERGE_UPDATE
    ]


@pytest.mark.asyncio
async def test_merge_pr_includes_issue_number(monkeypatch: pytest.MonkeyPatch) -> None:
    pm = _make_pr_manager()

    async def _ok(*_cmd: str, **_kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _ok)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #321: do the thing", "body")),
    )

    ok = await pm.merge_pr(321)

    assert ok is True
    events = _merge_update_events(pm)
    assert events, "merge_pr must publish a MERGE_UPDATE event"
    data = events[-1].data
    assert data["issue"] == 321, "MERGE_UPDATE must carry the issue number"
    assert data["pr"] == 321
    assert data["status"] == "merged"


@pytest.mark.asyncio
async def test_merge_pr_omits_issue_when_title_has_no_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-canonical title (no "#N") must not fabricate an issue number.
    pm = _make_pr_manager()

    async def _ok(*_cmd: str, **_kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _ok)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("chore: tidy up", "body")),
    )

    ok = await pm.merge_pr(7)

    assert ok is True
    data = _merge_update_events(pm)[-1].data
    assert "issue" not in data


@pytest.mark.asyncio
async def test_merge_pr_picks_the_fixed_issue_not_an_embedded_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A title that embeds a second reference must resolve to the issue the PR
    # FIXES (anchored on the keyword), never the first bare "#N".
    pm = _make_pr_manager()

    async def _ok(*_cmd: str, **_kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _ok)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #12: also touches #34", "body")),
    )

    ok = await pm.merge_pr(12)

    assert ok is True
    assert _merge_update_events(pm)[-1].data["issue"] == 12

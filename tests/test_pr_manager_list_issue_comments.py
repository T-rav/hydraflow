"""Regression: PRManager.list_issue_comments unpack + gh shape normalisation.

``_run_gh`` returns a single ``str``, but ``list_issue_comments`` unpacked it
as ``output, _ = await self._run_gh(...)`` — Python iterated the JSON string
and raised ``ValueError: too many values to unpack (expected 2)``, which the
broad ``except`` swallowed, so the method returned ``[]`` for every issue on
every call. Separately, ``gh issue view --json comments`` emits GraphQL-shaped
``author.login`` / ``createdAt`` (verified against issue #9275), not the
documented ``user.login`` / ``created_at`` — so even after the unpack fix the
preflight consumer would render ``?`` authors and empty timestamps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pr_manager import _normalise_issue_comment
from tests.helpers import make_pr_manager


@pytest.mark.asyncio
async def test_list_issue_comments_returns_normalised_comments(
    config, event_bus
) -> None:
    mgr = make_pr_manager(config, event_bus)
    gh_payload = json.dumps(
        {
            "comments": [
                {
                    "author": {"login": "alice"},
                    "body": "first",
                    "createdAt": "2026-06-05T01:00:00Z",
                },
                {
                    "author": {"login": "bob"},
                    "body": "second",
                    "createdAt": "2026-06-05T02:00:00Z",
                },
            ]
        }
    )
    mgr._run_gh = AsyncMock(return_value=gh_payload)

    comments = await mgr.list_issue_comments(42)

    assert [c["user"]["login"] for c in comments] == ["alice", "bob"]
    assert [c["body"] for c in comments] == ["first", "second"]
    assert comments[0]["created_at"] == "2026-06-05T01:00:00Z"


@pytest.mark.asyncio
async def test_list_issue_comments_empty_when_none(config, event_bus) -> None:
    mgr = make_pr_manager(config, event_bus)
    mgr._run_gh = AsyncMock(return_value=json.dumps({"comments": []}))

    assert await mgr.list_issue_comments(42) == []


def test_normalise_issue_comment_accepts_graphql_and_rest_shapes() -> None:
    graphql = _normalise_issue_comment(
        {"author": {"login": "gh"}, "body": "b", "createdAt": "T1"}
    )
    rest = _normalise_issue_comment(
        {"user": {"login": "rest"}, "body": "b", "created_at": "T2"}
    )

    assert graphql == {"user": {"login": "gh"}, "body": "b", "created_at": "T1"}
    assert rest == {"user": {"login": "rest"}, "body": "b", "created_at": "T2"}

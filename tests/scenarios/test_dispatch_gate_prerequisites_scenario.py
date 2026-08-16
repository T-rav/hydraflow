"""MockWorld scenario — dispatch gate on unmet issue Prerequisites (#11277).

Three implementer windows were burned dispatching issue #11277 before its
declared prerequisites (#11210, #11276) had merged: each implementer
discovered the same missing anchor files and exhausted its attempt cap. The
fix reads a "Prerequisites" declaration out of the issue body — via the real
``GitHubIssue.to_task()`` / ``parse_task_links`` path any actor's fetch cycle
goes through — and ``IssueStore._is_eligible`` defers dispatch until every
declared prerequisite has merged.

Integration-level: the issue body/labels come from the shared MockWorld
``FakeGitHub``, routed through the REAL ``GitHubIssue.to_task()`` conversion
(not hand-built ``Task`` objects), and the gate is the REAL
``IssueStore._is_eligible``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import IssueStore
from models import GitHubIssue
from tests.helpers import ConfigFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario

_BLOCKED_ISSUE = 11277
_PREREQ_A = 11210
_PREREQ_B = 11276
_READY = "hydraflow-ready"

_BODY = """## Problem

Slice 2 of the remainder.

**Prerequisites (both must merge first):**
- #11210 — creates the panel and the API surface this slice extends
- #11276 — the adapter this slice's button and CLI invoke

## Current State

Already landed from the prior slice.
"""


def _store() -> IssueStore:
    config = ConfigFactory.create(ready_label=[_READY])
    return IssueStore(config, AsyncMock(), EventBus())


def _route_from_github(world: MockWorld, store: IssueStore, number: int) -> None:
    """Route *number* into *store* the way a real fetch cycle would: read the
    issue's current body/labels off GitHub and run it through the same
    ``GitHubIssue.to_task()`` conversion ``GitHubTaskFetcher.fetch_all()``
    uses in production, so Prerequisites parsing is exercised for real."""
    issue = world.github.issue(number)
    gh_issue = GitHubIssue(
        number=number, title=issue.title, body=issue.body, labels=list(issue.labels)
    )
    store._route_issues([gh_issue.to_task()])


@pytest.mark.asyncio
async def test_issue_with_unmerged_prerequisites_is_not_dispatched(tmp_path) -> None:
    world = MockWorld(tmp_path)
    world.add_issue(_PREREQ_A, "Prereq A", "body", labels=[_READY])
    world.add_issue(_PREREQ_B, "Prereq B", "body", labels=[_READY])
    world.add_issue(_BLOCKED_ISSUE, "Fix Issue #11277", _BODY, labels=[_READY])

    store = _store()
    _route_from_github(world, store, _BLOCKED_ISSUE)

    assert store.get_implementable(10) == [], (
        "an issue whose declared prerequisites haven't merged must not be "
        "dispatched — the implementer has nothing to build against (#11277)"
    )


@pytest.mark.asyncio
async def test_issue_dispatches_once_both_prerequisites_merge(tmp_path) -> None:
    world = MockWorld(tmp_path)
    world.add_issue(_PREREQ_A, "Prereq A", "body", labels=[_READY])
    world.add_issue(_PREREQ_B, "Prereq B", "body", labels=[_READY])
    world.add_issue(_BLOCKED_ISSUE, "Fix Issue #11277", _BODY, labels=[_READY])

    store = _store()
    _route_from_github(world, store, _BLOCKED_ISSUE)
    assert store.get_implementable(10) == []

    # A prerequisite issue's PR merging is what actually flips the gate —
    # mark_merged is the same signal post_merge_handler/pr_unsticker/
    # review_phase use on a real merge.
    await world.github.close_issue(_PREREQ_A)
    store.mark_merged(_PREREQ_A)
    _route_from_github(world, store, _BLOCKED_ISSUE)
    assert store.get_implementable(10) == [], "still blocked on the second prerequisite"

    await world.github.close_issue(_PREREQ_B)
    store.mark_merged(_PREREQ_B)
    _route_from_github(world, store, _BLOCKED_ISSUE)
    assert [t.id for t in store.get_implementable(10)] == [_BLOCKED_ISSUE], (
        "once every declared prerequisite has merged, dispatch must resume"
    )

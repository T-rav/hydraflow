"""Regression (#11277): the dispatch loop must not burn attempt budget on an
issue whose declared prerequisites haven't merged yet.

Issue #11277 declared "**Prerequisites (both must merge first):** - #11210
... - #11276" in its body, but neither prerequisite had a PR, let alone a
merge, on staging. The queue/dispatch loop had no mechanism to read that
declaration, so three separate implementer windows (~3h of compute) picked
the issue up, discovered the missing anchor files from #11210/#11276, and
exhausted their attempt cap producing no usable diff.

This pins the fix end-to-end: a GitHub issue body carrying that exact
Prerequisites phrasing must route through ``GitHubIssue.to_task()`` into a
``BLOCKED_BY`` link, and ``IssueStore`` must exclude the issue from dispatch
until ``mark_merged`` fires for every declared prerequisite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from events import EventBus
from issue_store import IssueStore
from models import GitHubIssue, TaskLinkKind
from tests.helpers import ConfigFactory

_ISSUE_11277_BODY = """## Problem

Slice 2 (final) of the #11239 remainder.

**Prerequisites (both must merge first):**
- #11210 — creates `RepoHealthPanel.jsx`, `railsHealth.js`, and the
  `GET /api/rails-health` surface this slice extends (none exist on staging
  today)
- #11276 — the cross-repo `BotPRPort` adapter + `POST /api/rails-health/fix`
  this slice's button and CLI invoke

## Current State

Already landed (from the #11239 slice PR).
"""


def _store() -> IssueStore:
    config = ConfigFactory.create(ready_label=["hydraflow-ready"])
    return IssueStore(config, AsyncMock(), EventBus())


def test_issue_body_prerequisites_parse_to_blocked_by_links() -> None:
    issue = GitHubIssue(
        number=11277, title="Fix Issue #11277", body=_ISSUE_11277_BODY
    )
    task = issue.to_task()

    target_ids = {link.target_id for link in task.links}
    assert target_ids == {11210, 11276}
    assert all(link.kind == TaskLinkKind.BLOCKED_BY for link in task.links)


def test_issue_with_unmerged_prerequisites_is_not_dispatched() -> None:
    store = _store()
    issue = GitHubIssue(
        number=11277,
        title="Fix Issue #11277",
        body=_ISSUE_11277_BODY,
        labels=["hydraflow-ready"],
    )
    store._route_issues([issue.to_task()])

    assert store.get_implementable(10) == [], (
        "an issue with unmerged declared prerequisites must not be handed "
        "to an implementer — it cannot make progress"
    )


def test_issue_becomes_dispatchable_once_both_prerequisites_merge() -> None:
    store = _store()
    issue = GitHubIssue(
        number=11277,
        title="Fix Issue #11277",
        body=_ISSUE_11277_BODY,
        labels=["hydraflow-ready"],
    )
    store._route_issues([issue.to_task()])
    assert store.get_implementable(10) == []

    store.mark_merged(11210)
    assert store.get_implementable(10) == [], "still blocked on #11276"

    store.mark_merged(11276)
    assert [t.id for t in store.get_implementable(10)] == [11277], (
        "once every declared prerequisite has merged, dispatch must resume"
    )

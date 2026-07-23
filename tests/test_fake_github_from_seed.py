"""FakeGitHub.from_seed — construct a FakeGitHub from a MockWorldSeed."""

from __future__ import annotations

from mockworld.fakes import FakeGitHub
from mockworld.seed import MockWorldSeed


def test_from_seed_populates_issues() -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "body1", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "body2", "labels": ["y"]},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert set(gh._issues.keys()) == {1, 2}
    assert gh._issues[1].title == "first"
    assert gh._issues[2].labels == ["y"]


def test_from_seed_populates_prs() -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": []}],
        prs=[
            {
                "number": 100,
                "issue_number": 1,
                "branch": "hf/issue-1",
                "ci_status": "pass",
                "merged": False,
                "labels": ["wip"],
            },
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert 100 in gh._prs
    assert gh._prs[100].branch == "hf/issue-1"
    assert "wip" in gh._prs[100].labels


def test_from_seed_handles_empty_seed() -> None:
    gh = FakeGitHub.from_seed(MockWorldSeed())
    assert gh._issues == {}
    assert gh._prs == {}


def test_from_seed_honors_issue_state() -> None:
    """#9543: a ``state: closed`` seed issue reports COMPLETED from the port."""
    import asyncio

    seed = MockWorldSeed(
        issues=[
            {
                "number": 7301,
                "title": "done",
                "body": "b",
                "labels": [],
                "state": "closed",
            },
            {"number": 7302, "title": "open one", "body": "b", "labels": []},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert asyncio.run(gh.get_issue_state(7301)) == "COMPLETED"
    # Absent ``state`` key still defaults to open — back-compat preserved.
    assert asyncio.run(gh.get_issue_state(7302)) == "OPEN"


def test_from_seed_honors_issue_updated_at() -> None:
    """#9544: a seeded ``updated_at`` overrides FakeIssue's hard-coded default,
    so time-triggered loops (stale_issue_gc) can seed a genuinely fresh or
    genuinely stale issue instead of every issue reading equally stale."""
    seed = MockWorldSeed(
        issues=[
            {
                "number": 7701,
                "title": "stale",
                "body": "b",
                "labels": [],
                "updated_at": "2020-01-01T00:00:00Z",
            },
            {"number": 7702, "title": "no override", "body": "b", "labels": []},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert gh._issues[7701].updated_at == "2020-01-01T00:00:00Z"
    # Absent `updated_at` key still defaults to FakeIssue's own default —
    # back-compat preserved for every pre-#9544 seed.
    assert gh._issues[7702].updated_at == "2026-01-01T00:00:00Z"


def test_from_seed_honors_pr_mergeable() -> None:
    """#9543: ``mergeable: false`` seeds a CONFLICTING PR the watcher can act on."""
    import asyncio

    seed = MockWorldSeed(
        prs=[
            {
                "number": 8801,
                "issue_number": 8800,
                "branch": "agent/issue-8800",
                "mergeable": False,
            },
            {"number": 8802, "issue_number": 8803, "branch": "b2"},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    conflicting = asyncio.run(gh.list_conflicting_prs())
    assert [pr.number for pr in conflicting] == [8801]
    # Absent ``mergeable`` key still defaults to True — back-compat preserved.
    assert gh._prs[8802].mergeable is True

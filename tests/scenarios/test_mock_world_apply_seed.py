"""MockWorld.apply_seed populates the wired Fakes from a MockWorldSeed."""

from __future__ import annotations

import pytest

from mockworld.seed import MockWorldSeed


@pytest.mark.asyncio
async def test_apply_seed_populates_github_issues(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "b", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "b", "labels": ["y"]},
        ],
    )

    mock_world.apply_seed(seed)

    assert {i.number for i in mock_world._github._issues.values()} == {1, 2}


@pytest.mark.asyncio
async def test_apply_seed_populates_phase_scripts(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={
            "plan": {1: [{"success": True}]},
        },
    )

    mock_world.apply_seed(seed)

    # FakeLLM has the plan script populated for issue 1.
    assert 1 in mock_world._llm.planners._scripts


@pytest.mark.asyncio
async def test_apply_seed_builds_multi_runtime_registry(mock_world, tmp_path) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )

    mock_world.apply_seed(seed)

    registry = mock_world.registry
    assert set(registry.slugs) == {"owner-alpha", "owner-beta"}
    alpha = registry.get("owner-alpha")
    beta = registry.get("owner-beta")
    assert alpha.event_bus is not beta.event_bus  # genuinely independent runtimes
    assert alpha.event_bus._active_repo == "owner-alpha"  # tagged via set_repo


@pytest.mark.asyncio
async def test_apply_seed_threads_issue_state_and_pr_mergeable(mock_world) -> None:
    """#9543: closed issues and CONFLICTING PRs survive the Tier-1 loader."""
    seed = MockWorldSeed(
        issues=[
            {
                "number": 7301,
                "title": "done",
                "body": "b",
                "labels": [],
                "state": "closed",
            }
        ],
        prs=[
            {
                "number": 8801,
                "issue_number": 8800,
                "branch": "agent/issue-8800",
                "mergeable": False,
            }
        ],
    )

    mock_world.apply_seed(seed)

    assert await mock_world._github.get_issue_state(7301) == "COMPLETED"
    conflicting = await mock_world._github.list_conflicting_prs()
    assert [pr.number for pr in conflicting] == [8801]


@pytest.mark.asyncio
async def test_apply_seed_threads_issue_updated_at(mock_world) -> None:
    """#9544: a seeded per-issue ``updated_at`` reaches FakeIssue in the
    in-process (Tier 1) loader too — dual-loader parity with FakeGitHub.from_seed."""
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

    mock_world.apply_seed(seed)

    assert mock_world._github._issues[7701].updated_at == "2020-01-01T00:00:00Z"
    # Absent `updated_at` key still defaults to FakeIssue's own default.
    assert mock_world._github._issues[7702].updated_at == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_apply_seed_threads_rulesets(mock_world) -> None:
    """#9543: seeded rulesets reach FakeGitHub.fetch_rulesets in Tier 1 too."""
    seed = MockWorldSeed(
        rulesets={"main protect": {"name": "main protect", "enforcement": "active"}}
    )

    mock_world.apply_seed(seed)

    live = mock_world._github.fetch_rulesets("owner/repo")
    assert live["main protect"]["enforcement"] == "active"

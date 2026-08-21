"""ImplementPhase resolves the spawn timeout from triage's complexity tier (#11568)."""

from __future__ import annotations

from pathlib import Path

import pytest

from issue_cache import IssueCache
from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_implement_phase

ISSUE = 42


def _config(tmp_path: Path, *, agent_timeout: int = 3600):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        agent_timeout=agent_timeout,
    )


def _cache(tmp_path: Path, complexity: int | None) -> IssueCache:
    cache = IssueCache(tmp_path / "cache", enabled=True)
    if complexity is not None:
        cache.record_classification(
            ISSUE,
            issue_type="feature",
            complexity_score=complexity,
            complexity_rank="low",
            routing_outcome="plan",
        )
    return cache


async def _spawned_timeout(config, issue_cache: IssueCache | None) -> object:
    """Run one attempt and return the ``timeout_s`` the agent spawn received."""
    seen: list[object] = []

    async def recording_agent(issue, wt_path, branch, **kwargs):
        seen.append(kwargs.get("timeout_s", "missing"))
        return WorkerResultFactory.create(
            issue_number=issue.id,
            branch=branch,
            success=True,
            workspace_path=str(wt_path),
        )

    phase, _, _ = make_implement_phase(
        config,
        [TaskFactory.create(id=ISSUE)],
        agent_run=recording_agent,
        create_pr_return=PRInfoFactory.create(),
        issue_cache=issue_cache,
    )
    await phase.run_batch()
    assert len(seen) == 1
    return seen[0]


@pytest.mark.asyncio
async def test_no_cache_spawns_with_the_ceiling(tmp_path: Path) -> None:
    assert await _spawned_timeout(_config(tmp_path), None) == 3600


@pytest.mark.asyncio
async def test_unclassified_issue_spawns_with_the_ceiling(tmp_path: Path) -> None:
    assert await _spawned_timeout(_config(tmp_path), _cache(tmp_path, None)) == 3600


@pytest.mark.asyncio
async def test_tier_one_issue_spawns_with_half_the_ceiling(tmp_path: Path) -> None:
    assert await _spawned_timeout(_config(tmp_path), _cache(tmp_path, 1)) == 1800


@pytest.mark.asyncio
async def test_tier_five_issue_spawns_with_the_ceiling(tmp_path: Path) -> None:
    assert await _spawned_timeout(_config(tmp_path), _cache(tmp_path, 5)) == 3600


@pytest.mark.asyncio
async def test_tier_follows_the_configured_ceiling(tmp_path: Path) -> None:
    """A lower ``agent_timeout`` scales the tier — the table is relative."""
    config = _config(tmp_path, agent_timeout=1200)

    assert await _spawned_timeout(config, _cache(tmp_path, 3)) == 900


def test_implement_timeout_reads_the_latest_classification(tmp_path: Path) -> None:
    """Re-triage supersedes: the newest classification record wins."""
    cache = _cache(tmp_path, 1)
    cache.record_classification(
        ISSUE,
        issue_type="feature",
        complexity_score=7,
        complexity_rank="high",
        routing_outcome="plan",
    )
    phase, _, _ = make_implement_phase(_config(tmp_path), [], issue_cache=cache)

    assert phase._implement_timeout(TaskFactory.create(id=ISSUE)) == 3600

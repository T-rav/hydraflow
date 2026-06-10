"""Scenario: Phase 2/3 multi-repo AGGREGATE dashboard endpoints union real runtimes.

Tier-2 MockWorld layer for the Work Stream + HITL aggregations. The existing
unit tests use duck-typed ``make_registry``; these drive the routes through a
MockWorld-seeded registry of real runtimes (independent state / event_bus /
config per repo) under ``repo=__all__``. Seeded runtimes have ``orchestrator=
None`` and ``running=False``, so each test sets the minimal per-runtime stub the
endpoint needs (an orchestrator with the read method + ``running=True`` for the
active-gated routes), patches ``PRManager`` for the PR-shaped routes, and seeds
real per-repo state where the route enriches from it. Every case uses colliding
identifiers across the two repos to prove de-collision + repo-tagging.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mockworld.seed import MockWorldSeed
from models import HITLItem, LifetimeStats, PipelineStats, QueueStats, StageStats
from pr_manager import PRManager
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario

_REPOS = [("owner/alpha", "/tmp/owner-alpha"), ("owner/beta", "/tmp/owner-beta")]


def _seed_two_repos(mock_world):
    mock_world.apply_seed(MockWorldSeed(repos=_REPOS))
    return mock_world.registry.get("owner-alpha"), mock_world.registry.get("owner-beta")


def _router(config, event_bus, state, tmp_path, registry):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug=config.repo.replace("/", "-"),
    )
    return router


def _active_orch(*, queue=None, snapshot=None, pipeline_stats=None):
    """A minimal active orchestrator stub for the pipeline/queue routes."""
    orch = MagicMock()
    orch.issue_store.get_queue_stats = MagicMock(return_value=queue or QueueStats())
    orch.issue_store.get_pipeline_snapshot = MagicMock(return_value=snapshot or {})
    if pipeline_stats is not None:
        orch.build_pipeline_stats = MagicMock(return_value=pipeline_stats)
    return orch


@pytest.mark.asyncio
async def test_queue_sums_across_seeded_repos(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    alpha, beta = _seed_two_repos(mock_world)
    alpha.running = True
    alpha.orchestrator = _active_orch(queue=QueueStats(in_flight_count=2))
    beta.running = True
    beta.orchestrator = _active_orch(queue=QueueStats(in_flight_count=3))

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry), "/api/queue"
    )
    data = json.loads((await endpoint(repo="__all__")).body)

    assert data["in_flight_count"] == 5


@pytest.mark.asyncio
async def test_pipeline_unions_colliding_issue_tagged_by_repo(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    alpha, beta = _seed_two_repos(mock_world)
    # Issue #5 exists in BOTH repos — must render as two cards, not one.
    alpha.running = True
    alpha.orchestrator = _active_orch(snapshot={"ready": [{"issue_number": 5}]})
    beta.running = True
    beta.orchestrator = _active_orch(snapshot={"ready": [{"issue_number": 5}]})

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry),
        "/api/pipeline",
    )
    data = json.loads((await endpoint(repo="__all__")).body)

    # backend "ready" stage maps to frontend "implement".
    implement = data["stages"]["implement"]
    assert len(implement) == 2
    assert {i["issue_number"] for i in implement} == {5}
    assert {i["repo"] for i in implement} == {"owner-alpha", "owner-beta"}


@pytest.mark.asyncio
async def test_pipeline_stats_merges_across_seeded_repos(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    alpha, beta = _seed_two_repos(mock_world)
    a = PipelineStats(
        timestamp="2026-06-06T10:00:00",
        stages={"plan": StageStats(queued=2, active=1, worker_cap=3)},
    )
    b = PipelineStats(
        timestamp="2026-06-06T11:00:00",
        stages={"plan": StageStats(queued=1, active=2, worker_cap=2)},
    )
    alpha.running = True
    alpha.orchestrator = _active_orch(pipeline_stats=a)
    beta.running = True
    beta.orchestrator = _active_orch(pipeline_stats=b)

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry),
        "/api/pipeline/stats",
    )
    data = json.loads((await endpoint(repo="__all__")).body)

    assert data["stages"]["plan"]["queued"] == 3
    assert data["stages"]["plan"]["active"] == 3
    assert data["stages"]["plan"]["worker_cap"] == 5


@pytest.mark.asyncio
async def test_stats_sums_lifetime_across_seeded_repos(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    alpha, beta = _seed_two_repos(mock_world)
    alpha.state.get_lifetime_stats = lambda: LifetimeStats(issues_completed=3)
    beta.state.get_lifetime_stats = lambda: LifetimeStats(issues_completed=2)

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry), "/api/stats"
    )
    data = json.loads((await endpoint(repo="__all__")).body)

    assert data["issues_completed"] == 5


@pytest.mark.asyncio
async def test_hitl_unions_and_enriches_from_each_rows_state(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    alpha, beta = _seed_two_repos(mock_world)
    # Colliding issue #42; the HITL cause must come from each ROW's own state
    # (the Phase-3a latent-bug fix), not the default repo's.
    alpha.state.set_hitl_cause(42, "alpha cause")
    beta.state.set_hitl_cause(42, "beta cause")

    async def _fake_list_hitl(self, _labels):
        return [HITLItem(issue=42, title=f"{self._config.repo} bug", pr=101)]

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry), "/api/hitl"
    )
    with patch.object(PRManager, "list_hitl_items", _fake_list_hitl):
        data = json.loads((await endpoint(repo="__all__")).body)

    by_repo = {item["repo"]: item for item in data}
    assert set(by_repo) == {"owner-alpha", "owner-beta"}
    assert by_repo["owner-alpha"]["cause"] == "alpha cause"
    assert by_repo["owner-beta"]["cause"] == "beta cause"


@pytest.mark.asyncio
async def test_sandbox_hitl_unions_and_tags_seeded_repos(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    _seed_two_repos(mock_world)

    async def _fake_sandbox(prs):
        number = 101 if "alpha" in (prs._config.repo or "") else 202
        return {
            "items": [
                {
                    "number": number,
                    "branch": "b",
                    "url": "u",
                    "draft": False,
                    "type": "pr",
                }
            ]
        }

    endpoint = find_endpoint(
        _router(config, event_bus, state, tmp_path, mock_world.registry),
        "/api/sandbox-hitl",
    )
    with patch("dashboard_routes._hitl_routes.sandbox_hitl_handler", _fake_sandbox):
        data = json.loads((await endpoint(repo="__all__")).body)

    items = data["items"]
    assert {i["repo"] for i in items} == {"owner-alpha", "owner-beta"}
    assert {i["number"] for i in items} == {101, 202}

"""Scenario: the Phase 4 realtime REST aggregations union real per-repo runtimes.

Tier-2 MockWorld layer for the merged-feed backend. Unlike the duck-typed unit
tests (``test_dashboard_ws_merged_multirepo.py`` uses ``make_registry``), these
drive the actual routes through a MockWorld-seeded registry of real runtimes
(independent EventBus / StateTracker / config per repo), proving the
``resolve_runtimes`` fan-in + ``(timestamp, id)`` merge-sort + repo-tagging hold
end to end against colliding identifiers across repos:

* ``GET /api/events?repo=__all__`` — the reconnect backfill twin of the merged
  ``/ws`` stream — unions every runtime's event history, sorted and repo-tagged.
* ``GET /api/prs?repo=__all__`` — unions every runtime's open PRs, each tagged
  with its slug so the frontend de-collides same-number PRs across repos.

The merged ``/ws`` socket itself is covered at the unit (real EventBus via
``make_registry``) and browser (served ``/ws?repo=__all__``) tiers.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from events import EventType, HydraFlowEvent
from mockworld.seed import MockWorldSeed
from pr_manager import PRManager
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


def _evt(issue: int, ts: str) -> HydraFlowEvent:
    return HydraFlowEvent(
        type=EventType.WORKER_UPDATE, data={"issue": issue}, timestamp=ts
    )


@pytest.mark.asyncio
async def test_events_repo_all_unions_seeded_repo_histories(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    alpha = mock_world.registry.get("owner-alpha")
    beta = mock_world.registry.get("owner-beta")
    # Interleaved timestamps across the two real buses (set_repo tags each).
    await alpha.event_bus.publish(_evt(1, "2024-01-01T00:00:01+00:00"))
    await beta.event_bus.publish(_evt(1, "2024-01-01T00:00:02+00:00"))
    await alpha.event_bus.publish(_evt(2, "2024-01-01T00:00:03+00:00"))

    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=mock_world.registry,
        default_repo_slug=config.repo.replace("/", "-"),
    )
    endpoint = find_endpoint(router, "/api/events")

    data = json.loads((await endpoint(since=None, repo="__all__")).body)

    # Unioned, repo-tagged, and merge-sorted by (timestamp, id).
    assert [(e["repo"], e["data"]["issue"]) for e in data] == [
        ("owner-alpha", 1),
        ("owner-beta", 1),
        ("owner-alpha", 2),
    ]


@pytest.mark.asyncio
async def test_prs_repo_all_unions_and_tags_colliding_pr_numbers(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    # Both repos expose PR #7 (a cross-repo collision). The seeded runtimes have
    # no orchestrator, so get_prs reads each repo's PRManager.list_open_prs;
    # patch it to return the colliding PR for every runtime.
    async def _fake_list_open_prs(_self, _labels):
        return [
            {
                "pr": 7,
                "issue": 5,
                "branch": "agent/issue-5",
                "url": "https://example/pr/7",
                "draft": False,
                "title": "Shared number",
                "merged": False,
                "author": "bot",
            }
        ]

    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=mock_world.registry,
        default_repo_slug=config.repo.replace("/", "-"),
    )
    endpoint = find_endpoint(router, "/api/prs")

    with patch.object(PRManager, "list_open_prs", _fake_list_open_prs):
        data = json.loads((await endpoint(repo="__all__")).body)

    # The colliding PR #7 survives once per repo, each tagged with its slug.
    assert len(data) == 2
    assert all(p["pr"] == 7 for p in data)
    assert {p["repo"] for p in data} == {"owner-alpha", "owner-beta"}

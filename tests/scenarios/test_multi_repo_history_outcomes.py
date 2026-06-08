"""Scenario: /api/issues/history aggregates real per-repo outcomes for __all__.

Unlike the duck-typed unit test, this drives the actual route through a
MockWorld-seeded registry of real ``RepoRuntime`` objects (isolated config /
state / event bus per repo), proving the closure-threading + (repo, issue)
re-key hold end-to-end against colliding issue numbers across repos.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from events import EventType, HydraFlowEvent
from mockworld.seed import MockWorldSeed
from models import IssueOutcomeType
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


class _OfflineIssueFetcher:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def fetch_issue_by_number(self, issue_number: int) -> None:
        return None


@pytest.mark.asyncio
async def test_history_repo_all_aggregates_seeded_repo_outcomes(
    mock_world, config, event_bus, state, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("dashboard_routes._routes.IssueFetcher", _OfflineIssueFetcher)
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    alpha = mock_world.registry.get("owner-alpha")
    beta = mock_world.registry.get("owner-beta")
    await alpha.event_bus.publish(
        HydraFlowEvent(
            type=EventType.ISSUE_CREATED,
            data={"issue": 42, "title": "Alpha 42", "labels": ["epic:alpha"]},
        )
    )
    alpha.state.record_outcome(
        42, IssueOutcomeType.MERGED, reason="merged", pr_number=101, phase="review"
    )
    await beta.event_bus.publish(
        HydraFlowEvent(
            type=EventType.ISSUE_CREATED,
            data={"issue": 42, "title": "Beta 42", "labels": ["epic:beta"]},
        )
    )
    beta.state.record_outcome(
        42, IssueOutcomeType.HITL_APPROVED, reason="approved", phase="hitl"
    )

    default_slug = config.repo.replace("/", "-")
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=mock_world.registry,
        default_repo_slug=default_slug,
    )
    endpoint = find_endpoint(router, "/api/issues/history")

    payload = json.loads((await endpoint(repo="__all__", limit=500)).body)
    by_key = {(x["issue_number"], x["repo"]): x for x in payload["items"]}

    assert (42, "owner-alpha") in by_key
    assert (42, "owner-beta") in by_key
    assert by_key[(42, "owner-alpha")]["outcome"]["outcome"] == "merged"
    assert by_key[(42, "owner-beta")]["outcome"]["outcome"] == "hitl_approved"
    assert "owner/alpha" in by_key[(42, "owner-alpha")]["issue_url"]
    assert "owner/beta" in by_key[(42, "owner-beta")]["issue_url"]

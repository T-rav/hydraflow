"""Work Stream REST endpoints aggregate across repos for repo=__all__."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from models import QueueStats
from route_types import REPO_ALL
from tests.helpers import find_endpoint, make_dashboard_router, make_registry


def _runtime_spec(slug, *, snapshot=None, queue=None):
    orch = MagicMock()
    orch.running = True
    orch.issue_store.get_pipeline_snapshot = MagicMock(return_value=snapshot or {})
    orch.issue_store.get_queue_stats = MagicMock(return_value=queue or QueueStats())
    return {"slug": slug, "running": True, "orchestrator": orch}


@pytest.mark.asyncio
async def test_pipeline_unions_and_tags_by_repo(config, event_bus, state, tmp_path):
    registry = make_registry(
        _runtime_spec("owner-a", snapshot={"ready": [{"issue_number": 1}]}),
        _runtime_spec("owner-b", snapshot={"ready": [{"issue_number": 2}]}),
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/pipeline")

    resp = await endpoint(repo=REPO_ALL)
    data = json.loads(resp.body)

    # "ready" backend stage maps to frontend "implement"
    implement = data["stages"]["implement"]
    assert {i["issue_number"] for i in implement} == {1, 2}
    assert {i["repo"] for i in implement} == {"owner-a", "owner-b"}


@pytest.mark.asyncio
async def test_queue_sums_across_repos(config, event_bus, state, tmp_path):
    registry = make_registry(
        _runtime_spec("owner-a", queue=QueueStats(in_flight_count=2)),
        _runtime_spec("owner-b", queue=QueueStats(in_flight_count=3)),
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/queue")

    resp = await endpoint(repo=REPO_ALL)
    data = json.loads(resp.body)

    assert data["in_flight_count"] == 5


@pytest.mark.asyncio
async def test_pipeline_scopes_to_one_repo(config, event_bus, state, tmp_path):
    registry = make_registry(
        _runtime_spec("owner-a", snapshot={"ready": [{"issue_number": 1}]}),
        _runtime_spec("owner-b", snapshot={"ready": [{"issue_number": 2}]}),
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/pipeline")

    resp = await endpoint(repo="owner-a")
    data = json.loads(resp.body)

    implement = data["stages"]["implement"]
    assert {i["issue_number"] for i in implement} == {1}


@pytest.mark.asyncio
async def test_request_changes_rejects_all(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/api/request-changes", "POST")

    resp = await endpoint(
        {"issue_number": 1, "feedback": "x", "stage": "review"}, REPO_ALL
    )

    assert resp.status_code == 400

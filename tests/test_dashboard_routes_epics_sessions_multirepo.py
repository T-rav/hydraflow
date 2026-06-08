"""Epics + sessions endpoints aggregate across repos for repo=__all__."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from route_types import REPO_ALL
from tests.helpers import find_endpoint, make_dashboard_router, make_registry


def _orch_with_epic(epic_number: int) -> MagicMock:
    orch = MagicMock()
    detail = MagicMock(model_dump=lambda en=epic_number: {"epic_number": en})
    orch.epic_manager.get_all_detail = AsyncMock(return_value=[detail])
    return orch


def _state_with_session(slug: str) -> MagicMock:
    st = MagicMock()
    session = MagicMock(
        repo=slug, model_dump=lambda s=slug: {"id": f"{s}-1", "repo": s}
    )
    st.load_sessions = MagicMock(return_value=[session])
    return st


@pytest.mark.asyncio
async def test_epics_union_tagged_by_repo(config, event_bus, state, tmp_path):
    # Same epic_number in both repos must NOT collide — keyed by (repo, number).
    registry = make_registry(
        {"slug": "owner-a", "orchestrator": _orch_with_epic(1)},
        {"slug": "owner-b", "orchestrator": _orch_with_epic(1)},
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/epics")

    resp = await endpoint(repo=REPO_ALL)
    data = json.loads(resp.body)

    assert {(e["epic_number"], e["repo"]) for e in data} == {
        (1, "owner-a"),
        (1, "owner-b"),
    }


@pytest.mark.asyncio
async def test_epic_detail_rejects_all(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/api/epics/{epic_number}")

    resp = await endpoint(1, REPO_ALL)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_epic_release_rejects_all(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/api/epics/{epic_number}/release", "POST")

    resp = await endpoint(1, REPO_ALL)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sessions_union_across_repos(config, event_bus, state, tmp_path):
    registry = make_registry(
        {"slug": "owner-a", "state": _state_with_session("owner-a")},
        {"slug": "owner-b", "state": _state_with_session("owner-b")},
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    endpoint = find_endpoint(router, "/api/sessions")

    resp = await endpoint(repo=REPO_ALL)
    data = json.loads(resp.body)

    assert {s["repo"] for s in data} == {"owner-a", "owner-b"}

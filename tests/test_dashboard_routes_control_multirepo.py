"""System control endpoints aggregate across repos (Phase 3b).

``/api/control/status`` rolls up per-repo runtime status (with a ``repos`` list),
``/api/system/workers`` unions workers tagged by repo, ``clear-credit-pause``
fans out, and config writes are guarded (``repo=__all__`` and the process-global
``gh_circuit_breaker_enabled`` are rejected).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from route_types import REPO_ALL
from tests.conftest import make_state
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


def _repo_cfg(tmp_path, name: str) -> HydraFlowConfig:
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / name, repo=f"org/{name}")


def _orch(run_status: str, *, paused: datetime | None = None) -> MagicMock:
    orch = MagicMock()
    orch.run_status = run_status
    orch.credits_paused_until = paused
    orch.current_session_id = None
    orch._svc = None
    return orch


@pytest.mark.asyncio
async def test_control_status_rolls_up_across_repos(config, event_bus, state, tmp_path):
    paused_at = datetime(2026, 1, 2, tzinfo=UTC)
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": _orch("running"),
        },
        {
            "slug": "org-b",
            "config": _repo_cfg(tmp_path, "b"),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": _orch("credits_paused", paused=paused_at),
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    endpoint = find_endpoint(router, "/api/control/status")

    data = json.loads((await endpoint(repo=REPO_ALL)).body)

    # Per-repo breakdown present and tagged.
    assert {r["slug"] for r in data["repos"]} == {"org-a", "org-b"}
    # Rollup precedence: credits_paused > running.
    assert data["status"] == "credits_paused"
    assert data["credits_paused_until"] == paused_at.isoformat()


@pytest.mark.asyncio
async def test_control_status_scopes_to_one_repo(config, event_bus, state, tmp_path):
    cfg_b = _repo_cfg(tmp_path, "b")
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": _orch("idle"),
        },
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": _orch("running"),
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    endpoint = find_endpoint(router, "/api/control/status")

    data = json.loads((await endpoint(repo="org-b")).body)
    assert data["status"] == "running"
    assert data["config"]["repo"] == "org/b"
    assert data.get("repos", []) == []


@pytest.mark.asyncio
async def test_system_workers_union_tags_repo(config, event_bus, state, tmp_path):
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
        {
            "slug": "org-b",
            "config": _repo_cfg(tmp_path, "b"),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    endpoint = find_endpoint(router, "/api/system/workers")

    data = json.loads((await endpoint(repo=REPO_ALL)).body)
    repos_seen = {w["repo"] for w in data["workers"]}
    assert repos_seen == {"org-a", "org-b"}
    # Same worker name appears once per repo (union, not merged).
    names_a = [w["name"] for w in data["workers"] if w["repo"] == "org-a"]
    names_b = [w["name"] for w in data["workers"] if w["repo"] == "org-b"]
    assert names_a == names_b
    assert len(names_a) > 0


@pytest.mark.asyncio
async def test_clear_credit_pause_fans_out(config, event_bus, state, tmp_path):
    paused = datetime(2026, 1, 2, tzinfo=UTC)
    orch_a = _orch("credits_paused", paused=paused)
    orch_b = _orch("credits_paused", paused=paused)
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": orch_a,
        },
        {
            "slug": "org-b",
            "config": _repo_cfg(tmp_path, "b"),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": orch_b,
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    endpoint = find_endpoint(router, "/api/control/clear-credit-pause", "POST")

    resp = await endpoint(repo=REPO_ALL)
    assert resp.status_code == 200
    orch_a.clear_credit_pause.assert_called_once()
    orch_b.clear_credit_pause.assert_called_once()


@pytest.mark.asyncio
async def test_patch_config_rejects_all_repos(config, event_bus, state, tmp_path):
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    patch_config = find_endpoint(router, "/api/control/config", "PATCH")
    resp = await patch_config({"max_workers": 4}, repo=REPO_ALL)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_rejects_gh_circuit_breaker_per_repo(
    config, event_bus, state, tmp_path
):
    cfg_b = _repo_cfg(tmp_path, "b")
    registry = make_registry(
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    patch_config = find_endpoint(router, "/api/control/config", "PATCH")
    resp = await patch_config({"gh_circuit_breaker_enabled": False}, repo="org-b")
    assert resp.status_code == 400


def _two_repo_registry(event_bus, tmp_path, orch_a, orch_b):
    return make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": orch_a,
        },
        {
            "slug": "org-b",
            "config": _repo_cfg(tmp_path, "b"),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": orch_b,
        },
    )


def _router(config, event_bus, state, tmp_path, registry):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    return router


@pytest.mark.asyncio
async def test_control_status_all_idle_rolls_up_idle(
    config, event_bus, state, tmp_path
):
    registry = _two_repo_registry(event_bus, tmp_path, _orch("idle"), _orch("idle"))
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/control/status")
    data = json.loads((await endpoint(repo=REPO_ALL)).body)
    assert data["status"] == "idle"
    assert data["credits_paused_until"] is None


@pytest.mark.asyncio
async def test_control_status_selects_earliest_credits_paused_until(
    config, event_bus, state, tmp_path
):
    later = datetime(2026, 1, 5, tzinfo=UTC)
    earlier = datetime(2026, 1, 2, tzinfo=UTC)
    registry = _two_repo_registry(
        event_bus,
        tmp_path,
        _orch("credits_paused", paused=later),
        _orch("credits_paused", paused=earlier),
    )
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/control/status")
    data = json.loads((await endpoint(repo=REPO_ALL)).body)
    assert data["credits_paused_until"] == earlier.isoformat()


@pytest.mark.asyncio
async def test_system_workers_single_repo_tags_with_slug(
    config, event_bus, state, tmp_path
):
    registry = _two_repo_registry(event_bus, tmp_path, None, None)
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/system/workers")
    data = json.loads((await endpoint(repo="org-a")).body)
    assert {w["repo"] for w in data["workers"]} == {"org-a"}


@pytest.mark.asyncio
async def test_clear_credit_pause_single_not_paused_returns_400(
    config, event_bus, state, tmp_path
):
    registry = _two_repo_registry(
        event_bus, tmp_path, _orch("idle"), _orch("idle", paused=None)
    )
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/control/clear-credit-pause", "POST")
    resp = await endpoint(repo="org-b")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_clear_credit_pause_all_only_clears_paused(
    config, event_bus, state, tmp_path
):
    orch_a = _orch("credits_paused", paused=datetime(2026, 1, 2, tzinfo=UTC))
    orch_b = _orch("idle", paused=None)
    registry = _two_repo_registry(event_bus, tmp_path, orch_a, orch_b)
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/control/clear-credit-pause", "POST")
    resp = await endpoint(repo=REPO_ALL)
    assert json.loads(resp.body)["repos"] == ["org-a"]
    orch_a.clear_credit_pause.assert_called_once()
    orch_b.clear_credit_pause.assert_not_called()


@pytest.mark.asyncio
async def test_credit_refresh_fans_out(config, event_bus, state, tmp_path):
    from unittest.mock import AsyncMock, patch

    orch_a = _orch("credits_paused", paused=datetime(2026, 1, 2, tzinfo=UTC))
    orch_b = _orch("credits_paused", paused=datetime(2026, 1, 2, tzinfo=UTC))
    orch_a.try_clear_credit_pause.return_value = True
    orch_b.try_clear_credit_pause.return_value = True
    registry = _two_repo_registry(event_bus, tmp_path, orch_a, orch_b)
    router = _router(config, event_bus, state, tmp_path, registry)
    endpoint = find_endpoint(router, "/api/control/credit-refresh", "POST")

    with patch(
        "subprocess_util.probe_credit_availability",
        AsyncMock(return_value=True),
    ):
        data = json.loads((await endpoint(repo=REPO_ALL)).body)
    assert data["status"] == "resuming"
    assert set(data["repos"]) == {"org-a", "org-b"}

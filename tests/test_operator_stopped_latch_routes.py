"""POST /api/control/stop and /start persist the operator-stopped latch (#11208).

A deliberate ``Stop`` must survive relaunch and suppress boot-time autostart
(``factory_autostart.maybe_autostart_host``) until the operator explicitly
hits ``Start`` again. These tests cover both the registry (host-line) and the
legacy single-repo/test-wiring branches of the two control routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from tests.conftest import make_state
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


def _repo_cfg(tmp_path: Path, name: str) -> HydraFlowConfig:
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / name, repo=f"org/{name}")


# ---------------------------------------------------------------------------
# Registry branch (the production host-line path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_stop_sets_operator_stopped_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": True,
        },
    )
    host = registry.get("org-a")
    host.stop = AsyncMock()

    assert state.get_operator_stopped() is False

    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    stop = find_endpoint(router, "/api/control/stop")
    assert stop is not None

    response = await stop()

    assert json.loads(response.body)["status"] == "stopping"
    assert state.get_operator_stopped() is True


@pytest.mark.asyncio
async def test_registry_start_clears_operator_stopped_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    state.set_operator_stopped(True)

    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": False,
        },
    )
    host = registry.get("org-a")
    host.start = AsyncMock()

    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    start = find_endpoint(router, "/api/control/start")
    assert start is not None

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    assert state.get_operator_stopped() is False


@pytest.mark.asyncio
async def test_registry_start_clears_latch_even_when_already_running(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    """Idempotent Start (host already running) still clears the latch — the
    click itself is the operator's intent, whether or not it changed anything."""
    state.set_operator_stopped(True)

    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": True,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    start = find_endpoint(router, "/api/control/start")

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    assert state.get_operator_stopped() is False


@pytest.mark.asyncio
async def test_registry_stop_400_when_nothing_running_does_not_touch_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    """A Stop that fails (nothing running) is not a deliberate stop — the
    latch is left exactly as it was."""
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": False,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    stop = find_endpoint(router, "/api/control/stop")

    response = await stop()

    assert response.status_code == 400
    assert state.get_operator_stopped() is False


# ---------------------------------------------------------------------------
# Legacy single-repo/test wiring (no registry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_stop_sets_operator_stopped_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    orch = SimpleNamespace(running=True, request_stop=AsyncMock())
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: orch, registry=None
    )
    stop = find_endpoint(router, "/api/control/stop")

    response = await stop()

    assert json.loads(response.body)["status"] == "stopping"
    assert state.get_operator_stopped() is True


@pytest.mark.asyncio
async def test_legacy_start_clears_operator_stopped_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    state.set_operator_stopped(True)

    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: None, registry=None
    )
    start = find_endpoint(router, "/api/control/start")

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    assert state.get_operator_stopped() is False


# ---------------------------------------------------------------------------
# GET /api/control/status exposes the latch (ADR-0135) so the external
# liveness kernel — which cannot read StateTracker — can honour it too.
# ---------------------------------------------------------------------------


def _registry_router(config, event_bus, state, tmp_path: Path, *, running: bool):
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": running,
        },
    )
    host = registry.get("org-a")
    host.stop = AsyncMock()
    host.start = AsyncMock()
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    return router


@pytest.mark.asyncio
async def test_status_defaults_operator_stopped_false(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    router = _registry_router(config, event_bus, state, tmp_path, running=False)
    status = find_endpoint(router, "/api/control/status")

    data = json.loads((await status()).body)

    assert data["operator_stopped"] is False


@pytest.mark.asyncio
async def test_status_carries_operator_stopped_after_stop_and_clears_after_start(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    router = _registry_router(config, event_bus, state, tmp_path, running=True)
    stop = find_endpoint(router, "/api/control/stop")
    start = find_endpoint(router, "/api/control/start")
    status = find_endpoint(router, "/api/control/status")

    await stop()
    after_stop = json.loads((await status()).body)
    await start()
    after_start = json.loads((await status()).body)

    # The post-Stop shape the kernel sees: orchestrator gone ("idle") but the
    # latch set — the two must be distinguishable from a never-started boot.
    assert after_stop["operator_stopped"] is True
    assert after_start["operator_stopped"] is False


@pytest.mark.asyncio
async def test_all_repos_rollup_reports_the_factory_level_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    # Stop is factory-level (registry.stop_all) and persists the latch on the
    # HOST state, never on a per-repo state — so the rollup reports that one
    # host latch rather than OR-ing per-repo latches that are never set.
    router = _registry_router(config, event_bus, state, tmp_path, running=True)
    status = find_endpoint(router, "/api/control/status")

    before = json.loads((await status(repo="__all__")).body)
    state.set_operator_stopped(True)
    after = json.loads((await status(repo="__all__")).body)

    assert before["operator_stopped"] is False
    assert after["operator_stopped"] is True
    assert after["repos"], "rollup must still carry the per-repo breakdown"


@pytest.mark.asyncio
async def test_legacy_wiring_status_carries_latch(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    orch = SimpleNamespace(
        running=True, request_stop=AsyncMock(), current_session_id=None
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: orch, registry=None
    )
    stop = find_endpoint(router, "/api/control/stop")
    status = find_endpoint(router, "/api/control/status")

    await stop()
    data = json.loads((await status()).body)

    assert data["operator_stopped"] is True

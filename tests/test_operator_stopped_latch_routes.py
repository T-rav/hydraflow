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

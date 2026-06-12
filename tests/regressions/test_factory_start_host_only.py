"""Regression: the factory Start button must bring up the host line ONLY.

Two coupled bugs made it impossible to run the factory with only the host
(hydraflow) line active:

1. ``POST /api/control/start`` called ``registry.start_all()``, which booted
   the host AND every registered repo line. A factory must run fine with zero
   repos; repos are turned on individually via ``/api/runtimes/{slug}/start``
   once the factory is up.

2. ``orchestrator._running`` was set True *outside* ``run()``'s try/finally.
   When a line's run-task was cancelled during setup (e.g. by
   ``RepoRuntime.stop()``'s ``wait_for`` timeout firing before
   ``_supervise_loops`` was reached), the finally that resets ``_running``
   never executed — the line stayed stuck reporting ``running=True`` forever
   (``last_error=None``, since cancellation isn't an exception), so a stopped
   line showed green on the dashboard.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from orchestrator import HydraFlowOrchestrator
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


@pytest.mark.asyncio
async def test_global_start_starts_only_the_host_line(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    """POST /api/control/start starts the default/host line and no other repo."""
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_cfg(tmp_path, "a"),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "running": False,
        },
        {
            "slug": "org-b",
            "config": _repo_cfg(tmp_path, "b"),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "running": False,
        },
    )
    host = registry.get("org-a")
    repo = registry.get("org-b")
    host.start = AsyncMock()
    repo.start = AsyncMock()
    registry.start_all = AsyncMock()

    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    start = find_endpoint(router, "/api/control/start")
    assert start is not None

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    host.start.assert_awaited_once()
    repo.start.assert_not_called()
    registry.start_all.assert_not_called()


@pytest.mark.asyncio
async def test_global_start_is_idempotent_when_host_already_running(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    """Starting an already-running host line does not re-start it."""
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
    host.start = AsyncMock()

    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    start = find_endpoint(router, "/api/control/start")
    assert start is not None

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    host.start.assert_not_called()


@pytest.mark.asyncio
async def test_run_resets_running_when_cancelled_during_setup(
    config: HydraFlowConfig,
) -> None:
    """A run-task cancelled before _supervise_loops still clears _running."""
    orch = HydraFlowOrchestrator(config)
    reached_setup = asyncio.Event()
    release = asyncio.Event()

    async def blocking_publish_status() -> None:
        reached_setup.set()
        await release.wait()

    orch._publish_status = blocking_publish_status  # type: ignore[method-assign]

    task = asyncio.create_task(orch.run())
    await asyncio.wait_for(reached_setup.wait(), timeout=2)
    assert orch.running is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert orch.running is False

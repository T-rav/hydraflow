"""Regression: POST /api/control/start re-enables the pipeline workers (#11611).

Observed live 2026-08-21 ~22:30Z, right after the factory came up as a launchd
service: Start returned ``{"status": "started"}`` and ``operator_stopped``
went false, but ``disabled_workers`` stayed ``["plan", "triage"]``. The factory
ran with no path from the board to READY, and each worker had to be re-enabled
by hand through ``POST /api/control/bg-worker``.

Cause: the two branches of the route had diverged. The legacy (no-registry)
branch removed ``DEFAULT_PIPELINE_WORKERS`` from the disabled set; the
registry branch — the live production path — cleared only the latch.

Two things must hold, and the second is what actually bit:

1. The persisted set is cleaned, so a cold boot restores an enabled pipeline.
2. The live orchestrator's in-memory enabled map is flipped too.
   ``StateRestorer._restore_disabled_workers`` only ever ADDS disabled flags,
   and ``RepoRuntime.start()`` reuses the same orchestrator object across a
   stop/start — so a state-only clear would leave a restarted line still
   holding ``plan: False`` in memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


def _host_router(config, event_bus, state, tmp_path: Path, orch):
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    registry = make_registry(
        {
            "slug": "org-a",
            "config": ConfigFactory.create(repo_root=tmp_path / "a", repo="org/a"),
            "state": state,
            "event_bus": event_bus,
            "running": False,
        },
    )
    registry.get("org-a").start = AsyncMock()
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
        get_orch=lambda: orch,
    )
    return router


@pytest.mark.asyncio
async def test_registry_start_clears_the_persisted_pipeline_disables(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    state.set_operator_stopped(True)
    state.set_disabled_workers({"plan", "triage"})
    orch = SimpleNamespace(running=False, set_bg_worker_enabled=MagicMock())
    router = _host_router(config, event_bus, state, tmp_path, orch)
    start = find_endpoint(router, "/api/control/start")

    response = await start()

    assert json.loads(response.body)["status"] == "started"
    assert state.get_disabled_workers() == set()


@pytest.mark.asyncio
async def test_registry_start_reenables_them_on_the_live_orchestrator(
    config: HydraFlowConfig, event_bus, state, tmp_path: Path
) -> None:
    state.set_disabled_workers({"plan", "triage"})
    orch = SimpleNamespace(running=False, set_bg_worker_enabled=MagicMock())
    router = _host_router(config, event_bus, state, tmp_path, orch)
    start = find_endpoint(router, "/api/control/start")

    await start()

    assert sorted(c.args for c in orch.set_bg_worker_enabled.call_args_list) == [
        ("plan", True),
        ("triage", True),
    ]

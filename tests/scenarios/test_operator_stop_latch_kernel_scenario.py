"""MockWorld scenario: operator Stop holds the liveness kernel; a crash does not (ADR-0135).

End to end over the REAL seams: a ``RepoRuntime`` registered in a real
``RepoRuntimeRegistry`` with an orchestrator air-gapped to MockWorld's Fakes
(the wiring ``MockWorld._build_wired_orchestrator`` gives the dashboard's
Start button — same precedent as ``test_factory_autostart_scenario.py``),
driven through the production ``POST /api/control/{start,stop}`` and
``GET /api/control/status`` route handlers, with the status body fed to the
stdlib-only kernel's ``boot_guard.extract_status_fields`` +
``decide_boot_action`` exactly as ``probe_boot_correctness`` does (git facts
pinned to "verified correct", so only the status body decides).

1. operator Start → running → kernel NO_ACTION ("already active");
2. operator Stop → status reads idle/done (orchestrator gone) BUT
   ``operator_stopped`` is true → kernel NO_ACTION with the latch reason —
   the Stop is NOT undone;
3. operator Start again → latch cleared; then the line dies WITHOUT the
   operator (``orch.stop()`` directly — a crash stand-in) → status idle/done,
   latch false → kernel START. Down-recovery is intact; only a deliberate
   Stop is respected.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.liveness import boot_guard
from scripts.liveness.boot_guard import BootAction

from repo_runtime import RepoRuntime, RepoRuntimeRegistry
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = [pytest.mark.scenario, pytest.mark.timeout(90)]

_ORIGIN = "d" * 40
_STARTABLE = boot_guard.STARTABLE_STATUSES


async def _poll_until(condition, *, timeout_s: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"condition never became True within {timeout_s}s")


def _kernel_decision(status_body: dict[str, Any]) -> boot_guard.BootDecision:
    """The kernel's verdict for this status body on a verified-correct boot."""
    status, _sha, _behind, operator_stopped = boot_guard.extract_status_fields(
        status_body
    )
    return boot_guard.decide_boot_action(
        workspace_branch="staging",
        factory_branch="staging",
        origin_head=_ORIGIN,
        boot_sha=_ORIGIN,
        commits_behind=0,
        status=status,
        operator_stopped=operator_stopped,
    )


async def _status_body(status_endpoint) -> dict[str, Any]:
    body = json.loads((await status_endpoint()).body)
    # Pin the git facts the kernel would otherwise read from the workspace:
    # this scenario is about the STATUS body, not boot staleness.
    body.setdefault("config", {})
    body["config"]["boot_sha"] = _ORIGIN
    body["config"]["commits_behind"] = 0
    return body


@pytest.mark.asyncio
async def test_operator_stop_holds_kernel_and_crash_still_restarts(
    mock_world, tmp_path: Path
) -> None:
    config = mock_world.harness.config
    bus = mock_world.harness.bus
    state = mock_world.harness.state

    orch = await mock_world._build_wired_orchestrator(config, bus, state)
    host_runtime = RepoRuntime.from_shared(config, bus, state)
    host_runtime._orchestrator = orch
    registry = RepoRuntimeRegistry()
    registry.add(host_runtime)

    # The default-repo status resolves through the router's host-orchestrator
    # callable (server.py wires it to the host runtime's orchestrator); the
    # registry path is what Start/Stop drive.
    router, _ = make_dashboard_router(
        config,
        bus,
        state,
        tmp_path,
        get_orch=lambda: orch,
        registry=registry,
        default_repo_slug=host_runtime.slug,
    )
    start = find_endpoint(router, "/api/control/start")
    stop = find_endpoint(router, "/api/control/stop")
    status = find_endpoint(router, "/api/control/status")
    assert start is not None and stop is not None and status is not None

    try:
        # 1. Operator Start: running, no latch -> kernel leaves it alone.
        assert json.loads((await start()).body)["status"] == "started"
        await _poll_until(lambda: orch.run_status == "running")
        body = await _status_body(status)
        assert body["status"] == "running"
        assert body["operator_stopped"] is False
        assert _kernel_decision(body).action is BootAction.NO_ACTION

        # 2. Operator Stop: the orchestrator is gone, status reads like a
        #    never-started boot — only the latch tells the kernel to hold.
        assert json.loads((await stop()).body)["status"] == "stopping"
        await _poll_until(lambda: orch.run_status in _STARTABLE)
        body = await _status_body(status)
        assert body["status"] in _STARTABLE
        assert body["operator_stopped"] is True
        decision = _kernel_decision(body)
        assert decision.action is BootAction.NO_ACTION
        assert decision.action is not BootAction.START
        assert "operator stopped" in decision.reason
        assert decision.notify is False
        # And the pre-ADR-0135 reading of the same body WOULD have started it —
        # the latch is the load-bearing difference, not the status value.
        assert (
            _kernel_decision({**body, "operator_stopped": False}).action
            is BootAction.START
        )

        # 3. Operator Start again clears the latch; then the line dies without
        #    the operator (crash stand-in) -> kernel may START.
        assert json.loads((await start()).body)["status"] == "started"
        await _poll_until(lambda: orch.run_status == "running")
        assert (await _status_body(status))["operator_stopped"] is False

        await asyncio.wait_for(host_runtime.stop(), timeout=30.0)  # not via route
        await _poll_until(lambda: orch.run_status in _STARTABLE)
        body = await _status_body(status)
        assert body["status"] in _STARTABLE
        assert body["operator_stopped"] is False
        assert _kernel_decision(body).action is BootAction.START
    finally:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(host_runtime.stop(), timeout=15.0)

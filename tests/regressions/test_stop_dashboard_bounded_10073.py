"""Regression #10073: MockWorld.stop_dashboard must bound orchestrator.stop().

stop_dashboard awaited ``orchestrator.stop()`` with no timeout. Any task that
survives shutdown — or a real-orchestrator scenario whose stop path blocks —
wedged the in-process harness at event-loop close: pytest hung until the CI
job's 20-minute timeout with zero output (#10071's orphan probe showed
``WebSocketProtocol.run_asgi`` surviving stop_dashboard pre-fix).

These pins inject a deterministic hanging ``stop()`` fake with a tiny timeout
(no real sleeps near the timeout value) and assert the teardown fails LOUDLY —
a TimeoutError naming the live tasks — instead of hanging. The happy path pins
that a completing stop() produces no diagnostic and no error.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


class _HangingOrchestrator:
    """Orchestrator whose stop() parks forever (the #10073 wedge shape)."""

    running = True

    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        await asyncio.Event().wait()  # never set — deterministic hang


class _PromptOrchestrator:
    """Orchestrator whose stop() completes immediately (happy path)."""

    running = True

    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeDashboard:
    """Just enough dashboard surface for stop_dashboard: _orchestrator + stop()."""

    def __init__(self, orchestrator: object) -> None:
        self._orchestrator = orchestrator
        self._uvicorn_server = None
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _world_with_dashboard(
    tmp_path, orchestrator: object
) -> tuple[MockWorld, _FakeDashboard]:
    world = MockWorld(tmp_path)
    dashboard = _FakeDashboard(orchestrator)
    world._dashboard = dashboard
    world._dashboard_url = "http://127.0.0.1:1"
    return world, dashboard


async def test_hung_orchestrator_stop_raises_loud_timeout_with_task_names(
    tmp_path,
) -> None:
    # The exact #10073 shape: stop() never returns. Teardown must convert the
    # silent wedge into a bounded TimeoutError that names the live tasks —
    # the #10071 orphan-probe technique, applied to the timeout diagnostic.
    orchestrator = _HangingOrchestrator()
    world, _ = _world_with_dashboard(tmp_path, orchestrator)

    probe = asyncio.create_task(asyncio.Event().wait(), name="orphan-probe-10073")
    try:
        # Outer wait_for pins "no hang": a regressed unbounded await would
        # trip it with a bare TimeoutError that fails the match below.
        with pytest.raises(TimeoutError, match="orphan-probe-10073"):
            await asyncio.wait_for(
                world.stop_dashboard(orchestrator_stop_timeout=0.05), timeout=5
            )
    finally:
        probe.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await probe

    assert orchestrator.stop_calls == 1
    # The finally block must still clear the handles so a retried teardown
    # cannot double-stop a half-dead dashboard.
    assert world._dashboard is None
    assert world.dashboard_url is None


async def test_hung_orchestrator_stop_diagnostic_reaches_stderr(
    tmp_path, capsys
) -> None:
    # The attributed dump (task names) must land on stderr, where a CI log
    # shows it even if the exception is swallowed by an outer harness.
    world, _ = _world_with_dashboard(tmp_path, _HangingOrchestrator())

    with pytest.raises(TimeoutError):
        await world.stop_dashboard(orchestrator_stop_timeout=0.05)

    err = capsys.readouterr().err
    assert "orchestrator.stop() timed out" in err
    assert "live tasks" in err


async def test_completing_orchestrator_stop_is_quiet_and_clean(
    tmp_path, capsys
) -> None:
    # Happy path: stop() completes -> no TimeoutError, no diagnostic output,
    # dashboard fully torn down.
    orchestrator = _PromptOrchestrator()
    world, dashboard = _world_with_dashboard(tmp_path, orchestrator)

    await asyncio.wait_for(world.stop_dashboard(), timeout=5)

    assert orchestrator.stop_calls == 1
    assert dashboard.stopped is True
    assert world._dashboard is None
    assert world.dashboard_url is None
    assert "orchestrator.stop() timed out" not in capsys.readouterr().err

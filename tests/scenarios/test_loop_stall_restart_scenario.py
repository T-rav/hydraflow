"""Scenario: loop-stall restart-first control flow through MockWorld.

A registry loop goes silent → health monitor restarts it (no human paged);
still silent next sweep → exactly one `loop-stalled` escalation; heartbeat
recovers → the issue auto-closes and the markers re-arm. Dedup markers
persist across loop re-instantiation (DedupStore files), which each
`run_with_loops` call exercises by rebuilding the loop from the catalog.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bg_worker_manager import BGWorkerManager
from models import BackgroundWorkerState
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports

pytestmark = pytest.mark.scenario_loops


def _heartbeat(name: str, age_seconds: int) -> BackgroundWorkerState:
    stamp = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return BackgroundWorkerState(name=name, status="ok", last_run=stamp, details={})


class TestLoopStallRestartFirst:
    async def test_restart_then_escalate_then_recover(self, tmp_path):
        world = MockWorld(tmp_path)
        state = world.harness.state
        state.set_bg_worker_state("workspace_gc", _heartbeat("workspace_gc", 99_999))

        restart_calls: list[str] = []

        async def restart_cb(name: str) -> bool:
            restart_calls.append(name)
            return True

        stalled_loop = MagicMock()
        stalled_loop._get_default_interval.return_value = 600
        stalled_loop._cycle_timeout_seconds.return_value = 100
        # A real loop stamps this in run(); a MagicMock would auto-create a
        # non-datetime mock and break the max(heartbeat, run_started_at) math.
        stalled_loop._run_started_at = None
        bg_workers = BGWorkerManager(
            world.harness.config, state, {"workspace_gc": stalled_loop}
        )
        bg_workers.set_restart_cb(restart_cb)
        seed_ports(world, bg_workers=bg_workers)

        # Sweep 1 — stale: restart-first, nobody paged.
        await world.run_with_loops(["health_monitor"], cycles=1)
        assert restart_calls == ["workspace_gc"]
        assert await world.github.list_issues_by_label("loop-stalled") == []

        # Sweep 2 — restart didn't clear it: exactly one escalation,
        # no restart-thrash.
        await world.run_with_loops(["health_monitor"], cycles=1)
        stalled = await world.github.list_issues_by_label("loop-stalled")
        assert len(stalled) == 1
        assert "workspace_gc" in stalled[0]["title"]
        assert restart_calls == ["workspace_gc"]

        # Sweep 3 — dedup holds: still exactly one issue.
        await world.run_with_loops(["health_monitor"], cycles=1)
        assert len(await world.github.list_issues_by_label("loop-stalled")) == 1

        # Recovery — fresh heartbeat: auto-close + re-arm.
        state.set_bg_worker_state("workspace_gc", _heartbeat("workspace_gc", 5))
        await world.run_with_loops(["health_monitor"], cycles=1)
        assert await world.github.list_issues_by_label("loop-stalled") == []

        # A later fresh stall restarts again instead of escalating.
        state.set_bg_worker_state("workspace_gc", _heartbeat("workspace_gc", 88_888))
        await world.run_with_loops(["health_monitor"], cycles=1)
        assert restart_calls == ["workspace_gc", "workspace_gc"]
        assert await world.github.list_issues_by_label("loop-stalled") == []

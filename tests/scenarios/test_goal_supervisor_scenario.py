"""MockWorld scenario for the Tier-2 goal supervisor (ADR-0124).

Drives ``GoalSupervisorLoop`` end-to-end through the catalog:

* **idle healthy** — a fresh, all-``ok`` factory → the loop no-ops without
  consulting the Fable agent (``status: healthy``);
* **fires on degraded** — a worker heartbeat reporting ``error`` → the loop
  assembles the snapshot, routes the known-incident to a reversible restart
  nudge, and records it (``status: acted``, one nudge), firing the seeded
  ``bg_workers.restart`` verb.

Git reads are monkeypatched so the snapshot stays hermetic (no real
subprocess); the Fable runner is the catalog's air-gapped stub.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _hermetic_git(monkeypatch: Any) -> None:
    import git_revision

    monkeypatch.setattr(git_revision, "get_boot_sha", lambda: None)
    monkeypatch.setattr(git_revision, "get_commits_behind", lambda *a, **k: None)


def _heartbeat(status: str) -> dict[str, object]:
    return {
        "status": status,
        "last_run": _dt.datetime.now(_dt.UTC).isoformat(),
        "details": {},
    }


class _FakeBgWorkers:
    def __init__(self) -> None:
        self.restarted: list[str] = []

    async def restart(self, name: str) -> bool:
        self.restarted.append(name)
        return True


async def test_idle_healthy_is_noop(tmp_path, monkeypatch) -> None:
    _hermetic_git(monkeypatch)
    world = MockWorld(tmp_path)
    world._harness.state.set_worker_heartbeat("diagram_loop", _heartbeat("ok"))

    results = await world.run_with_loops(["goal_supervisor"], cycles=1)

    assert results["goal_supervisor"]["status"] == "healthy"


async def test_degraded_fires_and_nudges(tmp_path, monkeypatch) -> None:
    _hermetic_git(monkeypatch)
    world = MockWorld(tmp_path)
    bg = _FakeBgWorkers()
    _seed_ports(world, bg_workers=bg)
    world._harness.state.set_worker_heartbeat("flake_tracker", _heartbeat("error"))

    results = await world.run_with_loops(["goal_supervisor"], cycles=1)

    stats = results["goal_supervisor"]
    assert stats["status"] == "acted"
    assert stats["nudges"] >= 1
    # the reversible nudge actually restarted the errored loop
    assert bg.restarted == ["flake_tracker"]

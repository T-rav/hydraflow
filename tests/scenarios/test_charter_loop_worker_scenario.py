"""MockWorld scenario for CharterLoopWorkerLoop (#11866, ADR-0145).

The unit tests drive `_do_work` directly. This drives the loop through the real
LoopCatalog, so it covers the wiring a unit test cannot see: that the loop is
REGISTERED, that its scenario builder constructs it with a real runner, and
that receipts reach a writer through the whole chain.

Four outcomes, because the receipt vocabulary is the loop's actual product:
fire, skip-not-due, refuse-no-contract, and the dormant skip. A loop that
dispatched correctly but receipted nothing would look identical to one that did
nothing at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_V2 = """schema_version: 2
actors: agents/
loops:
  due-one:
    actor: worker
    enabled: true
    trigger:
      - cron: "0 * * * *"
    goal: run hourly
  dormant-one:
    actor: worker
    enabled: false
    trigger:
      - cron: "0 * * * *"
    goal: never
"""


def _repo(tmp_path: Path, *, with_contract: bool = True) -> Path:
    root = tmp_path / "target"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    if with_contract:
        (root / "agents" / "worker.md").write_text("YOU ARE THE WORKER")
    (root / "charter.yaml").write_text(_V2)
    return root


def _outcomes(receipts: list[str]) -> dict[str, str]:
    return {json.loads(line)["loop"]: json.loads(line)["outcome"] for line in receipts}


class TestCharterLoopWorker:
    async def test_a_due_loop_dispatches_and_receipts(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_loop_repos=[("o/r", _repo(tmp_path))])

        stats = await world.run_with_loops(["charter_loop_worker"], cycles=1)

        assert stats["charter_loop_worker"]["dispatched"] == 1
        outcomes = _outcomes(world._loop_ports["charter_loop_receipts"])
        assert outcomes["due-one"] == "ran"

    async def test_a_dormant_loop_is_receipted_not_omitted(self, tmp_path) -> None:
        """ "Dormant", "not due" and "nobody looked" must stay distinguishable.

        Omitting the dormant loop would make an operator unable to tell a
        declared-but-off loop from one the tick never reached.
        """
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_loop_repos=[("o/r", _repo(tmp_path))])

        await world.run_with_loops(["charter_loop_worker"], cycles=1)

        assert _outcomes(world._loop_ports["charter_loop_receipts"])["dormant-one"] == (
            "skipped-dormant"
        )

    async def test_an_unreadable_contract_refuses_and_dispatches_nothing(
        self, tmp_path
    ) -> None:
        """ADR-0145 Ruling 2, through the whole chain.

        A default prompt would produce plausible work attributed to an actor
        whose contract nobody could read — worse than no run, because it looks
        like one.
        """
        world = MockWorld(tmp_path)
        _seed_ports(
            world,
            charter_loop_repos=[("o/r", _repo(tmp_path, with_contract=False))],
        )

        await world.run_with_loops(["charter_loop_worker"], cycles=1)

        outcomes = _outcomes(world._loop_ports["charter_loop_receipts"])
        assert outcomes["due-one"] == "refused-no-contract"
        dispatch = world._loop_ports["charter_loop_dispatch"]
        assert not dispatch.called, (
            "the runner dispatched despite an unreadable contract"
        )

    async def test_a_second_cycle_does_not_re_dispatch_the_same_window(
        self, tmp_path
    ) -> None:
        """The catch-up policy, made durable by the dedup ledger.

        A factory ticking hourly against an hourly loop must fire once per
        window, not once per tick.
        """
        world = MockWorld(tmp_path)
        _seed_ports(world, charter_loop_repos=[("o/r", _repo(tmp_path))])

        stats = await world.run_with_loops(["charter_loop_worker"], cycles=2)

        # `run_with_loops` returns the LAST cycle's result.
        assert stats["charter_loop_worker"]["dispatched"] == 0

    async def test_an_unmigrated_repo_is_skipped(self, tmp_path) -> None:
        """Every repo today is unmigrated; failing them would make the loop
        permanently red on arrival."""
        root = tmp_path / "v1"
        root.mkdir()
        (root / "charter.yaml").write_text("schema_version: 1\n")

        world = MockWorld(tmp_path)
        _seed_ports(world, charter_loop_repos=[("o/r", root)])

        stats = await world.run_with_loops(["charter_loop_worker"], cycles=1)

        assert stats["charter_loop_worker"]["skipped_unmigrated"] == 1
        assert world._loop_ports["charter_loop_receipts"] == []

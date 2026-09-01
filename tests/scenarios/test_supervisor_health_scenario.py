"""Scenario: the health snapshot reads a working loop as working.

The unit tests prove `build_health_snapshot` exempts `running`, and separately
that `_polling_loop` records it. Neither sees the chain that actually failed:
loop tick -> heartbeat write -> persisted worker state -> snapshot -> verdict.

That chain is what produced the incident. On 2026-09-01 the supervisor reported
`healthy: false` three times running, with `error_loops: []` and vitals green,
because every loop's age was measured from its last COMPLETED tick. At 03:53 it
called `plan` stalled; at 03:54 the planner was emitting transcript lines for
issue #11544.

This drives the real orchestrator's real polling loop and feeds its real
recorded heartbeats to the real snapshot builder, with a work function that is
still in flight when the snapshot is taken.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from config import HydraFlowConfig
from orchestrator import HydraFlowOrchestrator
from supervisor_observation import build_health_snapshot

pytestmark = pytest.mark.scenario_loops


class TestALoopWorkingIsNotALoopStalled:
    async def test_a_tick_in_flight_reads_as_healthy(self, tmp_path) -> None:
        """The incident shape, through the real seam.

        The work function snapshots health from INSIDE the tick — the moment
        the old code got wrong. `last_run` is deliberately ancient: a loop that
        has been working for hours on one issue is exactly the case that was
        being misreported, and the whole point is that its age no longer
        decides the verdict.
        """
        config = HydraFlowConfig(repo="owner/repo", data_root=tmp_path)
        orch = HydraFlowOrchestrator(config)

        verdicts: list[Any] = []
        now = datetime.now(UTC)

        async def slow_work() -> bool:
            states = orch.get_bg_worker_states()
            heartbeats = {
                name: {
                    # `get_bg_worker_states()` returns DICTS. An attribute
                    # read here falls back to "ok" for every worker and the
                    # scenario silently tests nothing — it did, on the first
                    # draft, and reported the fix as broken.
                    "status": str(st["status"]),
                    # Ancient completion stamp: this loop has been busy for
                    # hours. Before the fix that alone condemned it.
                    "last_run": (now - timedelta(hours=8)).isoformat(),
                }
                for name, st in states.items()
            }
            verdicts.append(
                build_health_snapshot(
                    heartbeats=heartbeats,
                    intervals=dict.fromkeys(heartbeats, 30),
                    stall_multiplier=4,
                    now=now,
                )
            )
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("plan", slow_work, 10)

        assert verdicts, "the work function never ran — the seam did not fire"
        snap = verdicts[-1]

        # Assert the loop is PRESENT and reads as running, before asserting it
        # is not stalled. `stalled_loops == []` alone is satisfied just as well
        # by `plan` being absent from the heartbeats entirely — which is
        # exactly what happens with no in-flight write, so the first draft of
        # this scenario passed against the mutant it was written to catch.
        by_name = {lp.name: lp for lp in snap.loops}
        assert "plan" in by_name, (
            f"the loop never appeared in the snapshot at all: {list(by_name)}"
        )
        assert by_name["plan"].status == "running", (
            "the tick was not marked in flight, so the snapshot cannot tell "
            f"working from wedged: {by_name['plan']}"
        )
        assert snap.stalled_loops == [], (
            "a loop was reported stalled from inside its own running tick — "
            f"the incident shape, unchanged: {snap.stalled_loops}"
        )
        assert snap.healthy is True

    async def test_a_loop_that_finished_long_ago_is_still_caught(
        self, tmp_path
    ) -> None:
        """Anti-vacuity: the scenario must not prove the detector is off.

        Same chain, same ancient timestamp, but the tick has COMPLETED — the
        genuine wedge shape. If this also passed as healthy the fix would have
        removed the signal rather than corrected it.
        """
        config = HydraFlowConfig(repo="owner/repo", data_root=tmp_path)
        orch = HydraFlowOrchestrator(config)

        async def quick_work() -> bool:
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("plan", quick_work, 10)

        now = datetime.now(UTC)
        states = orch.get_bg_worker_states()
        heartbeats = {
            name: {
                "status": str(getattr(st, "status", "ok")),
                "last_run": (now - timedelta(hours=8)).isoformat(),
            }
            for name, st in states.items()
        }
        snap = build_health_snapshot(
            heartbeats=heartbeats,
            intervals=dict.fromkeys(heartbeats, 30),
            stall_multiplier=4,
            now=now,
        )

        assert snap.stalled_loops == ["plan"], (
            "a loop whose tick finished 8 hours ago is genuinely stalled and "
            f"must still be reported: {snap.stalled_loops}"
        )

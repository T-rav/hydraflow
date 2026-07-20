"""#9814 — deterministic background-loop first-tick staggering.

A restart used to fire every ``run_on_startup=False`` loop's first cycle —
and therefore every loop's GitHub reads — at the same instant (the
thundering-herd the gh circuit breaker kept tripping on). Each loop now
delays its first cycle by ``crc32(worker_name) % loop_startup_stagger_s``
seconds: deterministic across restarts, spread across the window.

Pins:
- Offset is deterministic, bounded by the spread, and per-worker.
- Spread 0 disables; ``run_on_startup=True`` loops are exempt (the
  ``github_cache`` poller must warm the shared cache at boot so staggered
  readers land on fresh data).
- ``run()`` waits the offset before the first cycle; stop during the
  stagger aborts cleanly; ``trigger()`` cuts the stagger short.
- Production default is 120s; the test ConfigFactory zeroes it so loop
  suites keep their cycle counts.
"""

from __future__ import annotations

import asyncio
import zlib
from typing import Any

import pytest

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventBus
from tests.helpers import ConfigFactory


class _StaggerProbeLoop(BaseBackgroundLoop):
    """Minimal concrete loop recording cycles; test-local, never wired."""

    def __init__(
        self,
        *,
        config: Any,
        deps: LoopDeps,
        worker_name: str = "stagger_probe",
        run_on_startup: bool = False,
    ) -> None:
        super().__init__(
            worker_name=worker_name,
            config=config,
            deps=deps,
            run_on_startup=run_on_startup,
        )
        self.cycles = 0

    async def _do_work(self) -> dict[str, Any] | None:
        self.cycles += 1
        return None

    def _get_default_interval(self) -> int:
        return 1

    def loop_fitness(self, ctx):  # pragma: no cover - not a wired loop
        return super().loop_fitness(ctx)


def _make(
    tmp_path,
    *,
    spread: int,
    worker_name: str = "stagger_probe",
    run_on_startup: bool = False,
    max_sleeps: int = 2,
):
    """Build a probe loop whose sleep_fn records durations then stops."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo", loop_startup_stagger_s=spread
    )
    stop_event = asyncio.Event()
    sleeps: list[float] = []

    async def _recording_sleep(seconds: float) -> None:
        sleeps.append(float(seconds))
        if len(sleeps) >= max_sleeps:
            stop_event.set()
        await asyncio.sleep(0)

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
        sleep_fn=_recording_sleep,
    )
    loop = _StaggerProbeLoop(
        config=config,
        deps=deps,
        worker_name=worker_name,
        run_on_startup=run_on_startup,
    )
    return loop, sleeps, stop_event


class TestStaggerOffset:
    def test_offset_deterministic_and_bounded(self, tmp_path) -> None:
        spread = 97
        loop_a, _, _ = _make(tmp_path, spread=spread, worker_name="flake_tracker")
        loop_b, _, _ = _make(tmp_path, spread=spread, worker_name="flake_tracker")
        loop_c, _, _ = _make(tmp_path, spread=spread, worker_name="rc_budget")

        offset_a = loop_a._startup_stagger_seconds()
        assert offset_a == loop_b._startup_stagger_seconds()
        assert 0 <= offset_a < spread
        assert offset_a == float(zlib.crc32(b"flake_tracker") % spread)
        assert 0 <= loop_c._startup_stagger_seconds() < spread

    def test_zero_spread_disables(self, tmp_path) -> None:
        loop, _, _ = _make(tmp_path, spread=0)
        assert loop._startup_stagger_seconds() == 0.0

    def test_run_on_startup_loops_exempt(self, tmp_path) -> None:
        """The github_cache poller must warm the cache at boot, unstaggered."""
        loop, _, _ = _make(tmp_path, spread=300, run_on_startup=True)
        assert loop._startup_stagger_seconds() == 0.0

    def test_production_default_and_test_factory_default(self, tmp_path) -> None:
        from config import HydraFlowConfig

        prod = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        assert prod.loop_startup_stagger_s == 120
        assert ConfigFactory.create(repo_root=tmp_path).loop_startup_stagger_s == 0


@pytest.mark.asyncio
class TestStaggerRun:
    async def test_run_sleeps_stagger_before_first_cycle(self, tmp_path) -> None:
        spread = 97
        loop, sleeps, _ = _make(
            tmp_path, spread=spread, worker_name="flake_tracker", max_sleeps=2
        )
        expected = float(zlib.crc32(b"flake_tracker") % spread)
        assert expected > 0  # guard: pick a worker whose offset is non-zero

        await loop.run()

        assert sleeps[0] == expected
        assert loop.cycles >= 1

    async def test_stop_during_stagger_prevents_first_cycle(self, tmp_path) -> None:
        loop, sleeps, _ = _make(
            tmp_path, spread=97, worker_name="flake_tracker", max_sleeps=1
        )

        await loop.run()

        # The single allowed sleep was the stagger; stop fired inside it,
        # so the loop exited without ever running a cycle.
        assert len(sleeps) == 1
        assert loop.cycles == 0

    async def test_trigger_during_stagger_cuts_it_short(self, tmp_path) -> None:
        loop, sleeps, stop_event = _make(
            tmp_path, spread=97, worker_name="flake_tracker", max_sleeps=99
        )

        async def _stop_after_first_cycle() -> None:
            while loop.cycles == 0:
                await asyncio.sleep(0)
            stop_event.set()
            loop.trigger()  # wake any pending interval sleep

        loop.trigger()  # pre-set: the stagger sleep is skipped entirely
        stopper = asyncio.create_task(_stop_after_first_cycle())
        await asyncio.wait_for(loop.run(), timeout=5)
        await stopper

        assert loop.cycles >= 1

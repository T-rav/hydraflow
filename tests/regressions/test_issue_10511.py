"""Regression #10511: a long implement build must not starve the free slot.

``ImplementPhase.run_batch``'s gated path drained + gated the ready queue
once at cycle start into a fixed list, then fed a fixed iterator to
``run_refilling_pool``. The pool's mid-run refill (#10312, via
``poll_interval``) re-calls the supply, but a fixed iterator never re-reads
the store — so issues that became ready DURING a long build could not fill
the free slot until the cycle ended. With ``max_workers=2`` and work queued,
only one slot ran while a long build held the cycle open.

The fix makes ``run_refilling_pool`` accept an async supply and has implement
live-pull + gate one ready issue per refill (the same live ``get_X(1)``
refill triage and plan already use). This pins the pool-level guarantee: with
an async supply, a mid-run-available item fills the free slot *while* a
long-running worker still holds its slot.
"""

from __future__ import annotations

import asyncio

import pytest

from phase_utils import run_refilling_pool


@pytest.mark.asyncio
async def test_async_supply_fills_free_slot_during_long_worker() -> None:
    started: list[int] = []
    # Only the slow item (1) is ready initially; the fast item (2) becomes
    # ready while the slow worker is still running — the exact starvation the
    # old drain-once-then-fixed-list gated path hit.
    available = [1]
    stop = asyncio.Event()

    async def async_supply() -> list[int]:
        await asyncio.sleep(0)
        return [available.pop(0)] if available else []

    async def worker(_idx: int, item: int) -> int:
        started.append(item)
        if item == 1:
            available.append(2)  # newly-ready work appears mid-run
            await asyncio.sleep(0.2)
        return item

    results = await run_refilling_pool(
        async_supply, worker, 2, stop, poll_interval=0.02
    )

    assert 2 in started, "mid-run-available item was not picked up mid-build"
    assert sorted(results) == [1, 2]


@pytest.mark.asyncio
async def test_run_refilling_pool_awaits_async_supply() -> None:
    """The pool awaits an async supply_fn (so a stage can live-pull + gate
    from the store on every refill instead of draining once up front)."""
    items = [1, 2, 3]
    stop = asyncio.Event()

    async def async_supply() -> list[int]:
        await asyncio.sleep(0)
        return [items.pop(0)] if items else []

    async def worker(_idx: int, item: int) -> int:
        return item

    results = await run_refilling_pool(async_supply, worker, 2, stop)
    assert sorted(results) == [1, 2, 3]

"""Regression test for issue #10296.

A PLAN-stage item could sit "queued" indefinitely while worker slots were
free. Root cause: ``run_refilling_pool`` (``src/phase_utils.py``) called
``supply_fn`` at the loop top and then blocked on
``asyncio.wait(..., FIRST_COMPLETED)``. If the queue was empty when the pool
filled (one long-running plan in flight) and an item was enqueued mid-run
(e.g. an eager triage→plan handoff via ``enqueue_transition``), the new item
was NOT picked up until the running task COMPLETED — even with free slots.

The fix adds an opt-in ``poll_interval`` to ``run_refilling_pool``. When set,
the pool wakes at least that often to re-run ``supply_fn`` into free slots,
dispatching mid-run work without waiting for the in-flight task to finish.
The plan phase opts in (bounded by the loop ``poll_interval``); callers that
don't pass it keep the original completion-only refill behavior.

This test is RED before the fix: the mid-run item never dispatches (the long
task only releases after dispatch), so the pool blocks forever and the guard
``wait_for`` raises ``TimeoutError``.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from phase_utils import run_refilling_pool


@pytest.mark.asyncio
async def test_midrun_enqueue_dispatched_before_inflight_completes() -> None:
    """Item enqueued mid-run is dispatched into a free slot within one poll
    window — not deferred until the in-flight long task completes."""
    max_concurrent = 3
    stop = asyncio.Event()
    long_started = asyncio.Event()
    long_release = asyncio.Event()
    new_dispatched = asyncio.Event()
    queue: list[int] = []
    supplied_long = False

    def supply() -> list[int]:
        nonlocal supplied_long
        if not supplied_long:
            supplied_long = True
            return [0]  # long-running item fills 1 of 3 slots
        if queue:
            return [queue.pop(0)]
        return []  # queue empty when the pool first fills

    async def worker(_idx: int, item: int) -> int:
        if item == 0:
            long_started.set()
            await long_release.wait()  # holds its slot open
            return item
        new_dispatched.set()  # a mid-run item ran in a free slot
        return item

    pool_task = asyncio.create_task(
        run_refilling_pool(supply, worker, max_concurrent, stop, poll_interval=0.01)
    )
    try:
        await asyncio.wait_for(long_started.wait(), timeout=2.0)
        # Enqueue a new item while the long task still holds its slot.
        queue.append(99)
        # Fix: dispatched before the long task completes. Without it, this
        # waits forever (the long task releases only after dispatch below).
        await asyncio.wait_for(new_dispatched.wait(), timeout=2.0)
        assert not long_release.is_set()  # long task still in flight
        long_release.set()
        results = await asyncio.wait_for(pool_task, timeout=2.0)
        assert sorted(results) == [0, 99]
    finally:
        long_release.set()
        stop.set()
        pool_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pool_task

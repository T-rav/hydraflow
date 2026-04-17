"""Regression test for issue #6710.

``run_concurrent_batch`` does not propagate ``AuthenticationError`` /
``CreditExhaustedError`` with immediate sibling cancellation.  When one worker
raises a fatal auth error, the exception is re-raised via ``await task``, but
sibling tasks are only cancelled in the ``finally`` block — **without awaiting
their cancellation**.  This means:

1. Sibling workers may continue executing (burning API credits) until the
   event loop processes the pending cancellation.
2. Sibling cleanup code (``except asyncio.CancelledError`` handlers) does not
   run before the caller sees the exception.

By contrast, ``run_refilling_pool`` explicitly detects fatal errors, cancels
all pending tasks, **awaits** their cancellation via ``asyncio.gather``, and
only then re-raises.

These tests are RED until ``run_concurrent_batch`` mirrors the
``run_refilling_pool`` pattern (cancel → gather → re-raise).
"""

from __future__ import annotations

import asyncio

import pytest

from phase_utils import run_concurrent_batch
from subprocess_util import AuthenticationError, CreditExhaustedError

# ---------------------------------------------------------------------------
# Tests — expect siblings to be cancelled AND awaited before re-raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6710 — fix not yet landed", strict=False)
async def test_auth_error_awaits_cancelled_siblings() -> None:
    """AuthenticationError must cancel AND await siblings before propagating.

    The sibling worker's CancelledError handler sets an event.  If
    ``run_concurrent_batch`` properly awaits cancelled tasks (like
    ``run_refilling_pool`` does), the event will be set before the
    AuthenticationError reaches the caller.

    BUG: the ``finally`` block cancels but does NOT await, so the
    handler never runs before the caller sees the exception.
    """
    stop = asyncio.Event()
    sibling_cleanup_ran = asyncio.Event()

    async def worker(idx: int, item: int) -> int:
        if item == 0:
            raise AuthenticationError("token expired")
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            sibling_cleanup_ran.set()
            raise
        return item

    with pytest.raises(AuthenticationError, match="token expired"):
        await run_concurrent_batch([0, 1], worker, stop)

    # If siblings were cancelled AND awaited, cleanup would have run.
    assert sibling_cleanup_ran.is_set(), (
        "run_concurrent_batch should await cancelled siblings before "
        "propagating AuthenticationError (like run_refilling_pool does)"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6710 — fix not yet landed", strict=False)
async def test_credit_exhausted_awaits_cancelled_siblings() -> None:
    """CreditExhaustedError must cancel AND await siblings before propagating."""
    stop = asyncio.Event()
    sibling_cleanup_ran = asyncio.Event()

    async def worker(idx: int, item: int) -> int:
        if item == 0:
            exc = CreditExhaustedError("credits exhausted")
            exc.resume_at = None
            raise exc
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            sibling_cleanup_ran.set()
            raise
        return item

    with pytest.raises(CreditExhaustedError, match="credits exhausted"):
        await run_concurrent_batch([0, 1], worker, stop)

    assert sibling_cleanup_ran.is_set(), (
        "run_concurrent_batch should await cancelled siblings before "
        "propagating CreditExhaustedError (like run_refilling_pool does)"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6710 — fix not yet landed", strict=False)
async def test_auth_error_all_siblings_fully_done() -> None:
    """After AuthenticationError, every sibling task must be done (not just cancelled).

    This catches the case where ``task.cancel()`` is called but the task is
    never awaited, leaving it in a cancelled-but-not-done limbo.
    """
    stop = asyncio.Event()
    created_tasks: list[asyncio.Task[int]] = []

    # Capture the tasks created inside run_concurrent_batch by wrapping
    # asyncio.create_task at the call site.
    _real_create_task = asyncio.create_task

    def _capturing_create_task(coro: object) -> asyncio.Task[int]:
        task = _real_create_task(coro)  # type: ignore[arg-type]
        created_tasks.append(task)
        return task

    async def worker(idx: int, item: int) -> int:
        if item == 0:
            raise AuthenticationError("bad token")
        await asyncio.sleep(100)
        return item

    import unittest.mock

    with unittest.mock.patch("phase_utils.asyncio.create_task", _capturing_create_task):
        with pytest.raises(AuthenticationError):
            await run_concurrent_batch([0, 1, 2], worker, stop)

    # All tasks should be fully resolved, not stuck in a pending state.
    for i, task in enumerate(created_tasks):
        assert task.done(), (
            f"Task {i} should be done after AuthenticationError, but it is "
            f"still pending — run_concurrent_batch must await cancelled tasks"
        )

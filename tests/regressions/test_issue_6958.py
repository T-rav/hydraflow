"""Regression test for issue #6958.

Bug: ``process_corrections`` iterates ``asyncio.as_completed`` with a bare
``await task``.  When a task raises a critical exception
(``AuthenticationError``, ``CreditExhaustedError``, ``MemoryError``), the
exception propagates unhandled and terminates the loop — remaining
corrections in the batch are silently dropped.

Expected behaviour (after fix): exceptions from individual tasks are caught
and logged; remaining corrections continue processing.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import make_hitl_phase


class TestIssue6958BatchExceptionDropsCorrections:
    """process_corrections must not abort the batch when one task raises."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6958 — fix not yet landed", strict=False)
    async def test_exception_in_one_task_does_not_abort_remaining(self, config) -> None:
        """Submit 3 corrections; one raises AuthenticationError.

        Acceptance criterion: process_corrections does NOT propagate the
        exception and the two healthy corrections are both processed.

        Current (buggy) behaviour: the bare ``await task`` propagates the
        exception out of the for-loop, aborting the batch.
        """
        from subprocess_util import AuthenticationError

        phase, *_ = make_hitl_phase(config)

        processed: set[int] = set()

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            if issue_number == 20:
                raise AuthenticationError("token expired")
            processed.add(issue_number)

        phase.submit_correction(10, "Fix A")
        phase.submit_correction(20, "Fix B")  # will raise
        phase.submit_correction(30, "Fix C")

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            # BUG: this raises AuthenticationError instead of catching it
            await phase.process_corrections()

        # If we reach here the exception was caught (good).
        # Verify every non-failing correction ran:
        assert processed == {10, 30}, (
            f"Expected both healthy corrections to run, but only got {processed}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6958 — fix not yet landed", strict=False)
    async def test_exception_does_not_lose_already_popped_corrections(
        self, config
    ) -> None:
        """Corrections are popped from _hitl_corrections before task creation.

        If process_corrections raises, the popped corrections are lost — they
        won't be retried on the next poll cycle.  This test verifies that
        after a batch with a failing task, no corrections are silently lost.
        """
        from subprocess_util import CreditExhaustedError

        phase, *_ = make_hitl_phase(config)

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            if issue_number == 50:
                raise CreditExhaustedError("limit reached")

        phase.submit_correction(40, "Fix X")
        phase.submit_correction(50, "Fix Y")  # will raise

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            # BUG: raises CreditExhaustedError
            await phase.process_corrections()

        # After processing, the failed correction should NOT have been
        # silently lost.  The corrections dict was cleared before task
        # creation (line 116-117), so if the batch aborts with an
        # exception the caller has no way to know issue 50 was dropped.
        # The fix should either re-enqueue or log — either way,
        # process_corrections must return normally.
        # (This assertion simply verifies the method returned without raising.)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6958 — fix not yet landed", strict=False)
    async def test_all_tasks_awaited_even_after_exception(self, config) -> None:
        """All created tasks must be properly awaited (no 'Task was destroyed
        but it is pending!' warnings) even when one raises."""
        from subprocess_util import AuthenticationError

        phase, *_ = make_hitl_phase(config)
        config.max_hitl_workers = 3  # allow full concurrency

        task_started = {10: False, 20: False, 30: False}

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            task_started[issue_number] = True
            if issue_number == 20:
                raise AuthenticationError("token expired")

        phase.submit_correction(10, "Fix A")
        phase.submit_correction(20, "Fix B")
        phase.submit_correction(30, "Fix C")

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            await phase.process_corrections()

        # Every task should have started (they were all created as
        # asyncio tasks).  The key assertion is that process_corrections
        # returned normally — with the bug it raises instead.
        assert all(task_started.values()), f"Not all tasks started: {task_started}"

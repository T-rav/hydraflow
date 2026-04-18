"""Regression test for issue #6694.

``adr_utils._assigned_adr_numbers`` is a module-level ``set[int]`` with no
lock.  Two concurrent callers of ``next_adr_number`` can both read ``highest``
before either writes to the set, causing both to return the **same** ADR
number — a silent collision.

The test forces this race window open by replacing the module-level set with
a custom ``BarrierSet`` subclass whose ``add`` method synchronises via a
``threading.Barrier``.  CPython's ``set.update()`` is implemented in C and
does NOT dispatch through ``self.add()``, so only the explicit ``.add(number)``
call on line 176 of ``adr_utils.py`` triggers the barrier — the earlier
``_assigned_adr_numbers.update(...)`` calls pass through unaffected.

Both threads compute ``number = highest + 1`` while the set still lacks the
other thread's number, then release simultaneously.  Under the bug, both
threads return the same value.

Expected: FAIL (both threads return the same number) until a lock is added.
"""

from __future__ import annotations

import pytest

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import adr_utils  # noqa: E402


class BarrierSet(set):
    """A set whose ``add()`` blocks at a threading barrier.

    This widens the race window in ``next_adr_number`` so that both
    threads have computed ``number = highest + 1`` before either thread
    records its number in the set.
    """

    def __init__(self, *args: object, barrier: threading.Barrier, **kwargs: object):
        super().__init__(*args, **kwargs)
        self._barrier = barrier

    def add(self, value: object) -> None:
        # Block until both threads reach this point.
        self._barrier.wait()
        super().add(value)


class TestIssue6694ConcurrentAdrNumberRace:
    """next_adr_number must hand out unique numbers under concurrency."""

    @pytest.mark.xfail(reason="Regression for issue #6694 — fix not yet landed", strict=False)
    def test_two_concurrent_callers_get_different_numbers(self, tmp_path: Path) -> None:
        """Simulate two coroutines calling next_adr_number at the same time.

        BUG: Without a lock, both threads read the same ``highest`` value
        from ``_assigned_adr_numbers`` and both compute ``highest + 1``,
        returning the same ADR number.

        Strategy: replace ``_assigned_adr_numbers`` with a ``BarrierSet``
        whose ``add()`` blocks at a 2-party barrier.  This guarantees
        Thread A's ``add`` hasn't executed when Thread B reads ``highest``,
        so both threads see the same max and produce a duplicate.
        """
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        # Seed with one existing ADR so highest starts at 1.
        (adr_dir / "0001-initial-decision.md").write_text("# Initial\n")

        # Snapshot and clear module-level state so the test is hermetic.
        saved_numbers = adr_utils._assigned_adr_numbers.copy()

        barrier = threading.Barrier(2, timeout=10)
        racy_set: set[int] = BarrierSet(barrier=barrier)

        # Swap in the barrier-instrumented set.
        adr_utils._assigned_adr_numbers = racy_set

        results: list[int | None] = [None, None]
        errors: list[BaseException | None] = [None, None]

        def worker(index: int) -> None:
            try:
                results[index] = adr_utils.next_adr_number(adr_dir)
            except BaseException as exc:
                errors[index] = exc

        try:
            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)
        finally:
            # Restore original module state.
            adr_utils._assigned_adr_numbers = set(saved_numbers)

        # Propagate thread errors.
        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"Worker {i} raised {err!r}") from err

        assert results[0] is not None and results[1] is not None, (
            f"Workers did not complete: results={results}"
        )
        assert results[0] != results[1], (
            f"DATA RACE: both concurrent callers got ADR number {results[0]}.  "
            f"_assigned_adr_numbers has no lock, so two readers both saw the "
            f"same highest value and returned identical numbers (issue #6694)."
        )

    def test_sequential_callers_get_different_numbers(self, tmp_path: Path) -> None:
        """Sanity check: sequential calls must always return unique numbers.

        This is not the race itself — it confirms the baseline works so
        the concurrent test failure is meaningful.
        """
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-initial-decision.md").write_text("# Initial\n")

        saved_numbers = adr_utils._assigned_adr_numbers.copy()
        adr_utils._assigned_adr_numbers.clear()
        try:
            n1 = adr_utils.next_adr_number(adr_dir)
            n2 = adr_utils.next_adr_number(adr_dir)
        finally:
            adr_utils._assigned_adr_numbers = set(saved_numbers)

        assert n1 != n2, f"Even sequential calls returned the same number: {n1}"
        assert n2 == n1 + 1, f"Expected n2={n1 + 1} but got {n2}"

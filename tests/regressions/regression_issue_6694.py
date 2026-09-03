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

import contextlib
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
        # Block until both threads reach this point — between computing
        # ``number`` and recording it, which is the only window where both
        # can still hold the same value.
        #
        # A timeout is EXPECTED once the fix lands: serialising the
        # read-compute-write means the second thread cannot reach this call
        # while the first is waiting, so the first times out and proceeds
        # alone. Raising there killed the test with BrokenBarrierError
        # instead of letting it report on the ADR numbers, which is what it
        # is actually about.
        with contextlib.suppress(threading.BrokenBarrierError):
            self._barrier.wait()
        super().add(value)


class TestIssue6694ConcurrentAdrNumberRace:
    """next_adr_number must hand out unique numbers under concurrency."""

    def test_two_concurrent_callers_get_different_numbers(self, tmp_path: Path) -> None:
        """Concurrent callers must never receive the same ADR number.

        The interleaving is FORCED. Two threads racing freely do not hit this
        window — measured: eight threads with the lock removed still produced
        eight distinct numbers on every run, because the critical section is
        short and the GIL serialises most of it. Moving the barrier to the
        directory scan did not help either; by then the threads had already
        re-serialised. Only a barrier BETWEEN computing the number and
        recording it holds both threads on the same value, which is what
        ``BarrierSet.add`` does.
        """
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-initial-decision.md").write_text("# Initial\n")

        saved_numbers = adr_utils._assigned_adr_numbers.copy()
        barrier = threading.Barrier(2, timeout=2)
        adr_utils._assigned_adr_numbers = BarrierSet(barrier=barrier)

        results: list[int | None] = [None, None]
        errors: list[BaseException | None] = [None, None]

        def worker(index: int) -> None:
            try:
                results[index] = adr_utils.next_adr_number(adr_dir)
            except BaseException as exc:  # noqa: BLE001
                errors[index] = exc

        try:
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        finally:
            adr_utils._assigned_adr_numbers = set(saved_numbers)

        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"Worker {i} raised {err!r}") from err
        assert all(r is not None for r in results), (
            f"workers did not complete: {results}"
        )
        assert results[0] != results[1], (
            f"DATA RACE: both concurrent callers got ADR number {results[0]}. "
            "The read-compute-write in next_adr_number must be serialised "
            "(issue #6694)."
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

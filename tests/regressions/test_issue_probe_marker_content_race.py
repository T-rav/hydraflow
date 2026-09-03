"""The teardown probe must wait for its marker's CONTENT, not its existence.

`_teardown_proof` spawns a child that does:

    p = open(marker, 'w')          # <- marker.exists() is True HERE
    child = subprocess.Popen(...)  # <- grandchild spawned
    p.write(f'{os.getpid()}\\n{child.pid}\\n')
    p.flush(); p.close()           # <- pids readable only HERE

The probe used to break its wait loop on `marker.exists()`, which goes true at
the `open()` — before either pid is written. On a loaded host the probe won
that race, read `[]`, and reported `descendants_spawned: 0` with a FAIL
verdict for a teardown that had worked perfectly.

That is a false negative in the PROBE, not merely a flaky test: `ok = bool(pids)
and not survivors` makes an empty read a failed proof of process-tree teardown.

Observed on a `make quality` run at 23-way parallelism:
`assert _probe_process_tree_teardown().observations["descendants_spawned"] >= 2`
-> `assert 0 >= 2`, passing in isolation every time.

Same class as #12101 one test over: observing a proxy for the thing (a file
exists / a pid is in the table) rather than the thing itself (the pids are
written / the process is reaped).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from director_capability_probe import _marker_pids


def test_a_created_but_unwritten_marker_reads_as_not_ready() -> None:
    """The exact instant that produced `descendants_spawned: 0`."""
    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    handle = marker.open("w")
    try:
        assert marker.exists(), "fixture wrong — the race needs the file to exist"

        assert _marker_pids(marker) == []
    finally:
        handle.close()


def test_a_half_written_marker_is_not_yet_the_tree() -> None:
    """A read landing between the two writes must not satisfy the wait."""
    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    marker.write_text("4242\n")

    assert len(_marker_pids(marker)) < 2


def test_a_torn_write_is_not_mistaken_for_pids() -> None:
    """A partial integer must read as not-ready, never crash the probe."""
    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    marker.write_text("4242\n7x")

    assert _marker_pids(marker) == []


def test_a_complete_marker_reads_both_pids() -> None:
    """The decoy: without it, every assertion above passes against a
    `_marker_pids` that always returns []."""
    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    marker.write_text("4242\n4243\n")

    assert _marker_pids(marker) == [4242, 4243]


def test_the_wait_blocks_until_the_pids_are_written() -> None:
    """Pins the WAIT, not just the read.

    Reverting the loop to `while not marker.exists()` leaves every assertion
    above green — the child normally writes fast enough that a quiet host
    never sees the gap. Only holding the file open and empty, then filling it
    from another thread, reproduces the loaded-host ordering deterministically.
    """
    import threading
    import time

    from director_capability_probe import _await_marker_pids

    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    handle = marker.open("w")  # exists, empty — the instant that broke the probe

    def _fill() -> None:
        time.sleep(0.3)
        handle.write("4242\n4243\n")
        handle.flush()

    writer = threading.Thread(target=_fill)
    writer.start()
    try:
        started = time.monotonic()
        pids = _await_marker_pids(marker, timeout_s=5.0)
        waited = time.monotonic() - started
    finally:
        writer.join()
        handle.close()

    assert pids == [4242, 4243], (
        "the wait returned before the pids were written — an exists()-based "
        "loop reads the empty file and reports descendants_spawned: 0"
    )
    assert waited >= 0.25, "returned too early to have actually waited"


def test_the_wait_gives_up_at_its_deadline() -> None:
    """It must not block forever on a child that never writes."""
    import time

    from director_capability_probe import _await_marker_pids

    marker = Path(tempfile.mkdtemp()) / "pids.txt"
    marker.write_text("")

    started = time.monotonic()
    pids = _await_marker_pids(marker, timeout_s=0.3)
    waited = time.monotonic() - started

    assert pids == []
    assert waited < 5.0, "the deadline did not bound the wait"

#!/usr/bin/env python3
"""Host-wide advisory lock for the full test suite (#11219).

Two concurrent ``make quality`` runs on one host oversubscribe the box:
xdist workers from both runs fight for cores and memory, the kernel (or
pytest's own timeouts) kills workers mid-run, and the survivor reports a
scatter of failures that pass in isolation. Tonight's session hit this
repeatedly — three separate "red" runs whose failures all passed on
rerun, costing more time than the suites themselves.

This wraps the suite in an ``flock``-style advisory lock: the second run
WAITS for the first instead of racing it. Waiting is strictly better than
a false red — a queued run finishes late, a contaminated run lies.

Usage (from the Makefile):
    python scripts/quality_host_lock.py -- <command...>

Behaviour:
- Acquires an exclusive lock on ``$TMPDIR/hydraflow-quality.lock``.
- Prints one line when it has to wait (so a stalled CI job is diagnosable).
- ``HYDRAFLOW_QUALITY_LOCK_TIMEOUT`` (seconds, default 3600) bounds the
  wait; on timeout it runs ANYWAY with a warning rather than failing the
  developer's command — the lock is advisory, not a gate.
- ``HYDRAFLOW_QUALITY_LOCK_DISABLE=1`` bypasses entirely (CI runners are
  already one-suite-per-box).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess  # nosec B404 - runs the caller's own quality command
import sys
import time
from pathlib import Path

LOCK_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "hydraflow-quality.lock"  # nosec B108
DEFAULT_TIMEOUT_S = 3600


def _is_make_dry_run() -> bool:
    """True when reached via `make -n/-t/-q` rather than a real build.

    GNU Make always executes a recipe line that references $(MAKE), even
    under -n/-t/-q (so recursive dry-runs can still print sub-make plans;
    see the `quality` Makefile target and #9875's regression test, which
    relies on this to inspect the `quality-unlocked` recipe). MAKEFLAGS
    carries the short-flag bundle through to this process's environment
    regardless. A dry run does no real suite work, so acquiring the lock
    would only risk deadlocking against an actual `make quality` run that
    already holds it — e.g. a nested `make -n quality` subprocess call
    made by a test while it itself runs under a real `make quality` (#11405).
    """
    first_token = os.environ.get("MAKEFLAGS", "").split(" ", 1)[0].lstrip("-")
    return any(flag in first_token for flag in "ntq")


def _acquire(handle, timeout_s: int) -> bool:
    """Block until the lock is held or *timeout_s* elapses. True if held."""
    deadline = time.monotonic() + timeout_s
    announced = False
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if not announced:
                print(
                    f"[quality-lock] another full suite is running on this "
                    f"host; waiting (up to {timeout_s}s) rather than racing "
                    f"it — concurrent suites SIGTERM each other (#11219)",
                    flush=True,
                )
                announced = True
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("usage: quality_host_lock.py -- <command...>", file=sys.stderr)
        return 2
    command = argv[argv.index("--") + 1 :]
    if not command:
        print("usage: quality_host_lock.py -- <command...>", file=sys.stderr)
        return 2

    if os.environ.get("HYDRAFLOW_QUALITY_LOCK_DISABLE") == "1" or _is_make_dry_run():
        return subprocess.call(command)  # nosec B603

    try:
        timeout_s = int(
            os.environ.get("HYDRAFLOW_QUALITY_LOCK_TIMEOUT", DEFAULT_TIMEOUT_S)
        )
    except ValueError:
        timeout_s = DEFAULT_TIMEOUT_S

    try:
        handle = LOCK_PATH.open("w")
    except OSError:
        # Unwritable lock path is never a reason to block a developer.
        return subprocess.call(command)  # nosec B603

    with handle:
        if not _acquire(handle, timeout_s):
            print(
                f"[quality-lock] wait exceeded {timeout_s}s — running anyway; "
                "results may be contaminated by the concurrent suite (#11219)",
                flush=True,
            )
        try:
            return subprocess.call(command)  # nosec B603
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

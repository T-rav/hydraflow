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
import signal
import subprocess  # nosec B404 - runs the caller's own quality command
import sys
import time
from pathlib import Path

LOCK_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "hydraflow-quality.lock"  # nosec B108
DEFAULT_TIMEOUT_S = 3600
# Distinct from any suite exit code: the suite did not run to completion,
# it was abandoned because the caller went away (#11434).
ORPHANED_EXIT = 75


class _Orphaned(Exception):
    """Raised when our parent exits while we are queueing for the lock."""


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


def _parent_pid_changed(initial_ppid: int) -> bool:
    """True once our parent has exited and we've been reparented (#11434).

    A wrapper whose parent is gone has no one left to read its exit code,
    so any work it goes on to do — waiting for the lock or running the
    suite — is pure waste on a shared host. Comparing against the pid we
    started with (rather than testing ``== 1``) also does the right thing
    under a subreaper, where an orphan is reparented to something else.
    """
    return os.getppid() != initial_ppid


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole group.

    The child is ``make``, which spawns pytest, which spawns xdist workers.
    Signalling ``make`` alone re-creates this very bug one level down, and
    SIGTERM is not enough — the observed orphans ignored it and had to be
    SIGKILLed.
    """
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def _run(command: list[str]) -> int:
    """Run *command*, abandoning it if our parent exits first (#11434)."""
    initial_ppid = os.getppid()
    try:
        poll_s = float(os.environ.get("HYDRAFLOW_QUALITY_LOCK_ORPHAN_POLL", "2"))
    except ValueError:
        poll_s = 2.0

    # start_new_session so the child leads its own process group and can be
    # killed as a unit without signalling ourselves.
    proc = subprocess.Popen(command, start_new_session=True)  # nosec B603
    try:
        while True:
            try:
                return proc.wait(timeout=poll_s)
            except subprocess.TimeoutExpired:
                pass
            if _parent_pid_changed(initial_ppid):
                print(
                    "[quality-lock] parent exited — abandoning the suite; "
                    "nobody is left to read the result (#11434)",
                    flush=True,
                )
                _kill_process_group(proc)
                return ORPHANED_EXIT
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)


def _acquire(handle, timeout_s: int) -> bool:
    """Block until the lock is held or *timeout_s* elapses. True if held."""
    deadline = time.monotonic() + timeout_s
    initial_ppid = os.getppid()
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
            if _parent_pid_changed(initial_ppid):
                # Orphaned while queueing. The run that spawned us has
                # already given up (and may have deleted the worktree we
                # were going to test in), so take the slot out of the
                # queue instead of draining it for a result nobody wants.
                print(
                    "[quality-lock] parent exited while waiting — leaving the "
                    "queue (#11434)",
                    flush=True,
                )
                raise _Orphaned from None
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
        return _run(command)

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
        return _run(command)

    with handle:
        try:
            held = _acquire(handle, timeout_s)
        except _Orphaned:
            return ORPHANED_EXIT
        if not held:
            print(
                f"[quality-lock] wait exceeded {timeout_s}s — running anyway; "
                "results may be contaminated by the concurrent suite (#11219)",
                flush=True,
            )
        try:
            return _run(command)
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

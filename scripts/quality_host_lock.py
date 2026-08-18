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
- Records its own parent pid at startup and abandons the moment it
  changes: leaves the queue if still waiting, or SIGKILLs the running
  suite's whole process group if already running (#11434). Without this,
  a wrapper whose launcher was killed (e.g. DiagnosticLoop ending an
  attempt) survives as a PID-1 orphan, going on queueing for — or
  running — a suite that nothing can ever read the result of.
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
POLL_INTERVAL_S = 2
ABANDONED_EXIT_CODE = 75  # sysexits.h EX_TEMPFAIL: orphaned, nobody to report to

_FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


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


def _run_command(command: list[str], parent_pid: int) -> int:
    """Run *command* as its own process group; abandon it if *parent_pid* dies.

    ``start_new_session=True`` makes the child a process-group leader, so
    the whole make -> pytest -> xdist-worker tree can be killed as a unit —
    signalling the direct child alone would leave grandchildren behind to
    reparent onto PID 1, recreating #11434 one level down. Forwarding
    SIGINT/SIGTERM/SIGHUP is required, not optional: start_new_session
    takes the suite out of the terminal's foreground process group, so
    those signals would otherwise never reach it at all.
    """
    proc = subprocess.Popen(command, start_new_session=True)  # nosec B603

    def _forward(signum: int, _frame: object) -> None:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(proc.pid, signum)
        sys.exit(128 + signum)

    previous_handlers = {
        sig: signal.signal(sig, _forward) for sig in _FORWARDED_SIGNALS
    }
    try:
        while True:
            try:
                return proc.wait(timeout=POLL_INTERVAL_S)
            except subprocess.TimeoutExpired:
                if os.getppid() != parent_pid:
                    with contextlib.suppress(ProcessLookupError, OSError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    print(
                        f"[quality-lock] parent process ({parent_pid}) exited "
                        "while the suite was running; killed the suite's "
                        "process group and abandoning (#11434)",
                        flush=True,
                    )
                    return ABANDONED_EXIT_CODE
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def _acquire(handle, timeout_s: int, parent_pid: int) -> str:
    """Block until the lock is held, the wait times out, or *parent_pid* dies.

    Returns "acquired", "timeout", or "abandoned". Comparing the live
    ``os.getppid()`` against the caller-recorded *parent_pid* — rather than
    testing ``os.getppid() == 1`` — is what keeps this correct under a
    subreaper, where an orphan is reparented onto the subreaper's pid
    instead of onto init's.
    """
    deadline = time.monotonic() + timeout_s
    announced = False
    while True:
        if os.getppid() != parent_pid:
            return "abandoned"
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return "acquired"
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
                return "timeout"
            time.sleep(POLL_INTERVAL_S)


def main(argv: list[str]) -> int:
    parent_pid = os.getppid()

    if "--" not in argv:
        print("usage: quality_host_lock.py -- <command...>", file=sys.stderr)
        return 2
    command = argv[argv.index("--") + 1 :]
    if not command:
        print("usage: quality_host_lock.py -- <command...>", file=sys.stderr)
        return 2

    if os.environ.get("HYDRAFLOW_QUALITY_LOCK_DISABLE") == "1" or _is_make_dry_run():
        return _run_command(command, parent_pid)

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
        return _run_command(command, parent_pid)

    with handle:
        state = _acquire(handle, timeout_s, parent_pid)
        if state == "abandoned":
            print(
                f"[quality-lock] parent process ({parent_pid}) exited while "
                "queueing; leaving the queue rather than running for nobody "
                "(#11434)",
                flush=True,
            )
            return ABANDONED_EXIT_CODE
        if state == "timeout":
            print(
                f"[quality-lock] wait exceeded {timeout_s}s — running anyway; "
                "results may be contaminated by the concurrent suite (#11219)",
                flush=True,
            )
        try:
            return _run_command(command, parent_pid)
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

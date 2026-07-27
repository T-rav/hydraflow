"""Orphaned pytest-worker reaper for the Tier-1 liveness kernel (#10734).

A dead or OOM-killed ``make`` build can leave ``pytest -n auto`` (xdist) worker
processes reparented to ``init`` (``ppid == 1``). They keep holding memory and,
on the next build, re-OOM the host. This module finds those orphans and SIGKILLs
them — deterministically, behind a positive-int / not-self / not-init pid guard
re-derived locally (the kernel cannot import ``src/process_group.py``).

A PURE selection core (:func:`select_orphan_pids`) over a ``ps`` snapshot, plus a
thin I/O edge (:func:`enumerate_processes`, :func:`reap_orphans`).

Stdlib only — must not import ``src/``.
"""

from __future__ import annotations

import os
import signal
import subprocess

#: Only reap orphans that have clearly outlived a build. A live xdist worker of
#: the CURRENT run always has a non-init parent (so ``ppid == 1`` already
#: excludes it); the age floor is a second guard against racing a build that is
#: mid-teardown.
DEFAULT_AGE_FLOOR_SECONDS = 300
PS_TIMEOUT_SECONDS = 10.0

#: The parent pid of a reparented orphan on both macOS and Linux.
_INIT_PID = 1


def self_pids() -> frozenset[int]:
    """Pids that must never be signalled: this process and its parent."""
    return frozenset({os.getpid(), os.getppid()})


def is_reapable_pid(pid: object) -> bool:
    """True only for a genuine, safe-to-kill pid.

    Mirrors ``src/process_group.py::is_real_pid`` (re-derived, not imported):
    ``bool`` is excluded (``True`` is an ``int``), ``0`` (the caller's own group)
    and negatives (pgid syntax) are rejected, and ``1`` (init) plus self/parent
    are never signalled — so a fabricated pid can never SIGKILL init or the
    kernel itself.
    """
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > _INIT_PID
        and pid not in self_pids()
    )


def parse_etime_seconds(etime: str) -> int | None:
    """Parse a ``ps`` ``etime`` field (``[[dd-]hh:]mm:ss``) into whole seconds.

    Returns None on any malformed value — fail-closed: an unparseable age is
    "unknown", which the selector excludes from reaping.
    """
    raw = etime.strip()
    if not raw:
        return None
    days = 0
    if "-" in raw:
        day_part, _, raw = raw.partition("-")
        try:
            days = int(day_part)
        except ValueError:
            return None
    try:
        nums = [int(part) for part in raw.split(":")]
    except ValueError:
        return None
    if len(nums) == 2:
        hours, minutes, seconds = 0, nums[0], nums[1]
    elif len(nums) == 3:
        hours, minutes, seconds = nums[0], nums[1], nums[2]
    else:
        return None
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def looks_like_pytest_worker(command: str) -> bool:
    """True if a process command line is a pytest invocation.

    Substring match on ``pytest`` is deliberately broad: combined with the
    ``ppid == 1`` and age-floor guards in :func:`select_orphan_pids`, any
    orphaned, long-outlived pytest process is a leaked test tree worth reaping.
    An interactively-run pytest always has a live shell parent (``ppid != 1``)
    and is never selected.
    """
    return "pytest" in command.lower()


def select_orphan_pids(
    ps_output: str, *, age_floor_seconds: int = DEFAULT_AGE_FLOOR_SECONDS
) -> list[int]:
    """Pure: pids of orphaned (``ppid == 1``) pytest processes past the age floor.

    ``ps_output`` is the raw text of ``ps -Ao pid,ppid,etime,command`` — a header
    line followed by one process per line. Malformed lines, non-orphans, young
    processes, and non-pytest commands are all skipped.
    """
    selected: list[int] = []
    for line in ps_output.splitlines()[1:]:  # [1:] drops the ps header row.
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        pid_str, ppid_str, etime_str, command = fields
        try:
            pid = int(pid_str)
            ppid = int(ppid_str)
        except ValueError:
            continue
        if ppid != _INIT_PID:
            continue
        if not is_reapable_pid(pid):
            continue
        if not looks_like_pytest_worker(command):
            continue
        age = parse_etime_seconds(etime_str)
        if age is None or age < age_floor_seconds:
            continue
        selected.append(pid)
    return selected


def enumerate_processes(*, timeout: float = PS_TIMEOUT_SECONDS) -> str | None:
    """Snapshot processes via ``ps``; raw stdout or None. Never raises.

    ``ps`` is absent on nothing HydraFlow supports, but a missing binary,
    non-zero exit, or timeout all degrade to None (reap nothing this tick).
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["ps", "-Ao", "pid,ppid,etime,command"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def reap_orphans(pids: list[int]) -> list[int]:
    """SIGKILL each reapable pid; return those actually signalled. Never raises.

    Every pid is re-checked against :func:`is_reapable_pid` immediately before
    the kill, so even a caller that passes an unvetted list can never signal
    init or the kernel's own process.
    """
    killed: list[int] = []
    for pid in pids:
        if not is_reapable_pid(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            continue
        killed.append(pid)
    return killed

"""The single process-group kill primitive (#9641).

Every subprocess HydraFlow spawns uses ``start_new_session=True``, making
the child its own process-group leader (``pid == pgid``), so killing the
GROUP — not just the direct child — is what reaps grandchildren (sub-make,
pytest workers, agent CLIs).

This lives in exactly one place because the guard is load-bearing and was
independently re-derived (with different strengths) three times in one
night (#9648, #9911, #10002-CI): ``os.killpg`` against a fabricated pid is
catastrophic — a mock proc's auto-created ``.pid`` coerces to ``1`` via
``__index__``, and a pid-``0`` fake signals the CALLER'S OWN process
group, killing the test runner mid-suite. The architecture test
``tests/architecture/test_process_group_kill_guard.py`` forbids
``os.killpg`` anywhere else in ``src/``.
"""

from __future__ import annotations

import contextlib
import os
import signal
from typing import Any, TypeGuard


def _self_pids() -> frozenset[int]:
    """Live/self PIDs that a freshly spawned child can never legitimately be.

    Every HydraFlow subprocess uses ``start_new_session=True``, so a real
    reapable child is its own group leader with a brand-new pid — it can never
    equal ``1`` (init/namespace-PID-1), the runner's own pid, its parent's pid,
    or the runner's process-GROUP id. A fabricated/mocked ``.pid`` can equal any
    of them, and ``os.killpg`` against one SIGKILLs a live, sensitive group:
    ``killpg(1)`` tears down init (delivered on a root Linux CI container; a
    benign ``EPERM`` on non-root macOS, which is why the bug is invisible
    locally), and ``killpg(getpgrp())``/``killpg(getpid())`` SIGKILL the test
    runner's own process group mid-suite — the #10393 ``Coverage (trailing)``
    hang. Excluding them is purely defensive and can never reject a legitimate
    grandchild group. Total by contract (``is_real_pid`` runs before the
    ``kill_process_group`` suppression), so the lookups are wrapped.
    """
    pids = {1}
    for getter in (os.getpid, os.getppid, os.getpgrp):
        with contextlib.suppress(OSError):
            pids.add(getter())
    return frozenset(pids)


def is_real_pid(pid: object) -> TypeGuard[int]:
    """True only for a genuine positive integer pid safe to ``os.killpg``.

    ``bool`` is excluded explicitly (``True`` is an ``int`` and passes a
    naive ``isinstance`` check); ``0`` targets the caller's own group and
    negative values are pgid syntax — never signal any of them. Live/self
    pids (``1``, this process, its parent, its process group — see
    ``_self_pids``) are excluded so a fabricated ``.pid`` can never make the
    reaper SIGKILL init or the runner's own group (#10393).
    """
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and pid not in _self_pids()
    )


def kill_process_group(proc: object, sig: signal.Signals = signal.SIGKILL) -> None:
    """Best-effort signal to *proc*'s whole process group; never raises.

    Non-real pids (mock doubles, unstarted processes) take the child-only
    ``proc.kill()`` fallback — old semantics for fakes, group semantics
    for real children. ``ProcessLookupError``/``OSError`` (group already
    gone, permissions) are suppressed so the caller's ``TimeoutError`` /
    ``CancelledError`` propagates instead.
    """
    with contextlib.suppress(ProcessLookupError, OSError):
        pid = getattr(proc, "pid", None)
        if is_real_pid(pid):
            os.killpg(pid, sig)
        else:
            kill = getattr(proc, "kill", None)
            if callable(kill):
                kill()


# ---------------------------------------------------------------------------
# Runtime-wide registry of live children (#9911 follow-up).
#
# stream_claude_process registers its spawns via runner_utils (which aliases
# this set), and HostRunner.run_simple registers here directly — so the
# stop/shutdown reaper sees EVERY live child regardless of spawn path. It
# lives in this module because execution.py cannot import runner_utils
# (runner_utils imports execution) and this is the shared stdlib-only home.
# ---------------------------------------------------------------------------

_TRACKED: set[Any] = set()


def track(proc: object) -> None:
    """Register a live child for stop-path reaping."""
    _TRACKED.add(proc)


def untrack(proc: object) -> None:
    """Deregister a child (its spawn path finished normally)."""
    _TRACKED.discard(proc)


def reap_all_tracked(sig: signal.Signals = signal.SIGKILL) -> int:
    """Group-kill every tracked live child; returns how many were reaped."""
    live = [proc for proc in list(_TRACKED) if getattr(proc, "returncode", 0) is None]
    for proc in live:
        kill_process_group(proc, sig)
    _TRACKED.clear()
    return len(live)

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


def is_real_pid(pid: object) -> bool:
    """True only for a genuine positive integer pid.

    ``bool`` is excluded explicitly (``True`` is an ``int`` and passes a
    naive ``isinstance`` check); ``0`` targets the caller's own group and
    negative values are pgid syntax — never signal any of them.
    """
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


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

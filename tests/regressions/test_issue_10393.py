"""Regression: Coverage (trailing) CI hang — is_real_pid admitted sensitive PIDs (#10393).

The ``Coverage (trailing)`` job (single-threaded, ``-p no:xdist``, the only lane
that runs ``tests/regressions/`` in the same process as the rest of ``tests/``)
was CANCELLED ~90s before its 30-min timeout with ZERO ``FAILED`` lines: pytest
was still "running" when GitHub Actions killed it, and its buffered output was
lost. That fingerprint — cancelled-at-timeout, no failures, clean on local
macOS — is the #9983/#10002 signature of ``os.killpg`` reaching a live, sensitive
process group through a fabricated/mocked ``.pid``.

``is_real_pid`` (``src/process_group.py``) is the single guard every reap path
funnels through before ``os.killpg``. It rejected ``bool``/``0``/negatives but
ADMITTED ``1`` (init), ``os.getpid()``, ``os.getppid()`` and ``os.getpgrp()``
(the caller's OWN process group). A test double whose ``.pid`` coerces to any of
those sails through ``is_real_pid`` and ``os.killpg`` SIGKILLs the group:

* ``killpg(os.getpgrp())`` / ``killpg(os.getpid())`` when the runner is its own
  group leader → SIGKILLs the pytest process group mid-suite. Lethal on BOTH
  Linux and macOS (signalling your own group is never permission-gated) — the
  job simply dies with no traceback.
* ``killpg(1)`` → EPERM on non-root macOS (silently suppressed → the bug is
  INVISIBLE locally) but delivered on a root Linux CI container. The
  platform divergence is the tell, not noise.

A freshly spawned child (every HydraFlow subprocess uses
``start_new_session=True``, so ``child.pid == child.pgid``) can NEVER equal a
live process's pid — init, the runner, its parent, or the runner's group leader —
so excluding those four is purely defensive against fabricated pids and can
never reject a legitimate grandchild group.

Bounded + safe: ``os.killpg`` is spied (never invoked for real), so this test
asserts the guard REJECTS the sensitive pids instead of actually signalling any
group. On the unfixed guard the spy is called with the sensitive pid and the
assertion fails (RED); with the fix the child-only fallback is taken (GREEN).
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from process_group import is_real_pid, kill_process_group  # noqa: E402


def _sensitive_pids() -> dict[str, int]:
    """The live/self PIDs a legitimate start_new_session child can never be."""
    return {
        "init": 1,
        "own_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "own_process_group": os.getpgrp(),
    }


class _FakeProc:
    """Stands in for a subprocess whose .pid was fabricated/mocked."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.killed = False

    def kill(self) -> None:  # child-only fallback — the SAFE path
        self.killed = True


class TestIsRealPidRejectsSensitivePids:
    @pytest.mark.parametrize(
        "name", ["init", "own_pid", "parent_pid", "own_process_group"]
    )
    def test_sensitive_pid_is_not_real(self, name: str) -> None:
        pid = _sensitive_pids()[name]
        assert is_real_pid(pid) is False, (
            f"is_real_pid admitted {name}={pid}; os.killpg({pid}) would signal a "
            f"live, sensitive process group"
        )

    def test_ordinary_positive_pid_still_real(self) -> None:
        # Over-broad exclusion would break legitimate grandchild-group reaping.
        assert is_real_pid(424242) is True


class TestKillProcessGroupNeverSignalsSensitiveGroup:
    @pytest.mark.parametrize(
        "name", ["init", "own_pid", "parent_pid", "own_process_group"]
    )
    def test_sensitive_pid_takes_child_only_fallback(self, name: str) -> None:
        pid = _sensitive_pids()[name]
        proc = _FakeProc(pid=pid)
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc)
        killpg.assert_not_called()  # RED on the unfixed guard (it called killpg(pid))
        assert proc.killed is True  # SAFE child-only fallback was used instead

    def test_real_pid_still_group_killed(self) -> None:
        proc = _FakeProc(pid=424242)
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc)
        killpg.assert_called_once_with(424242, signal.SIGKILL)
        assert proc.killed is False

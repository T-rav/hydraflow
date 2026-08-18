"""Regression: the quality host lock must not outlive its parent (#11434).

Observed live on 2026-08-18. ``DiagnosticLoop`` retried issue #11303 every
cycle; each attempt ran ``make quality`` through this wrapper, and when the
attempt failed the loop tore down the worktree ("Destroyed workspace ...")
without reaping the subprocess. The runner killed ``make``, but the
``uv run``/wrapper layer underneath survived, got reparented to PID 1, and
kept queueing for the host lock from a directory that no longer existed.

One leaked every ~2 minutes. Twelve had accumulated before anyone noticed,
each holding a slot in a lock queue that drains far slower than it fills,
and the 15-minute load average reached 12.6. SIGTERM did not clear them —
the ``uv run`` wrapper ignored it — so they had to be SIGKILLed by hand.

The wrapper now watches for its parent's exit and abandons the suite: once
the parent is gone nobody will ever read the result, so continuing only
burns the host.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quality_host_lock.py"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def test_parent_pid_changed_detects_reparenting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The predicate is a plain identity check on our parent pid."""
    sys.path.insert(0, str(_SCRIPT.parent))
    import quality_host_lock as qhl

    monkeypatch.setattr(qhl.os, "getppid", lambda: 4242)
    assert qhl._parent_pid_changed(4242) is False
    assert qhl._parent_pid_changed(99) is True


def test_orphaned_wrapper_abandons_the_suite_and_kills_its_child(
    tmp_path: Path,
) -> None:
    """Killing the wrapper's parent must take the whole suite down with it.

    Without this, the wrapper survives its parent and keeps holding (or
    queueing for) the host lock, which is exactly how twelve orphans piled
    up while the loop that spawned them had already moved on.
    """
    marker = tmp_path / "child_started"
    # The inner command outlives the test unless the watchdog kills it, so
    # it announces itself first — that lets us assert it really ran (and so
    # the watchdog killed a live process rather than winning a startup race).
    inner = f"import pathlib,time; pathlib.Path({str(marker)!r}).touch(); time.sleep(300)"

    env = {
        **os.environ,
        # A dedicated lock file: this test must not queue behind (or block)
        # a real suite running on the same host.
        "TMPDIR": str(tmp_path),
        "HYDRAFLOW_QUALITY_LOCK_ORPHAN_POLL": "0.2",
    }
    env.pop("HYDRAFLOW_QUALITY_LOCK_DISABLE", None)
    env.pop("MAKEFLAGS", None)

    # A shell that lingers briefly, then exits — so the wrapper captures a
    # real parent pid first and is orphaned afterwards. Exiting immediately
    # would race the wrapper's own startup and it would simply be born with
    # ppid 1, which is a different (and legitimate) situation.
    pidfile = tmp_path / "wrapper.pid"
    launcher = subprocess.Popen(
        [
            "sh",
            "-c",
            f'{sys.executable} {_SCRIPT} -- {sys.executable} -c "$INNER" & '
            f"echo $! > {pidfile}; sleep 3",
        ],
        env={**env, "INNER": inner},
    )
    launcher.wait(timeout=30)

    wrapper_pid = int(pidfile.read_text().strip())
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and _alive(wrapper_pid):
        time.sleep(0.2)

    assert marker.exists(), (
        "the inner command never started — the test raced startup and would "
        "pass even if the watchdog did nothing"
    )
    assert not _alive(wrapper_pid), (
        f"quality_host_lock (pid {wrapper_pid}) outlived its parent — this is "
        "the leak that put twelve orphans on the host"
    )

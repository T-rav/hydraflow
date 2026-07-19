"""Regression (#9648): HostRunner.run_simple must reap subprocess GRANDCHILDREN
on timeout, not just the direct child.

run_simple spawns the model/agent CLI (the direct child), which in turn forks
its own helpers (sub-make, pytest, agent workers — the grandchildren). The old
timeout path spawned WITHOUT ``start_new_session=True`` and called plain
``proc.kill()``, reaping only the top-level process. The grandchildren were
re-parented to init and kept running, holding file handles and burning tokens
against an already-abandoned cycle — the identical defect #9579 fixes in the
caretaker loops.

The fix spawns with ``start_new_session=True`` (child becomes a process-group
leader, pid == pgid) and, on timeout, reaps the whole group via
``os.killpg(proc.pid, SIGKILL)``.

Mocks cannot prove a process group was actually torn down, so this is a real
subprocess test: it spawns a child that forks a long-lived grandchild, records
the grandchild's PID, forces a timeout, and asserts the grandchild is gone.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from execution import HostRunner


def _pid_alive(pid: int) -> bool:
    """True if *pid* names a live (non-reaped) process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another uid — still alive.
        return True
    return True


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX process groups / os.killpg are not available on Windows.",
)
@pytest.mark.asyncio
async def test_run_simple_timeout_reaps_grandchild(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"

    # bash is the direct child of the Python process. ``sleep 300 &`` is the
    # grandchild; its PID is written to *pidfile*. ``wait`` blocks bash so the
    # whole tree outlives the timeout.
    script = f"sleep 300 & echo $! > {pidfile}; wait"

    runner = HostRunner()
    with pytest.raises(TimeoutError):
        await runner.run_simple(["bash", "-c", script], timeout=0.5)

    # The grandchild PID should have been recorded before the timeout fired.
    deadline = time.monotonic() + 5.0
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pidfile.exists(), "grandchild never recorded its PID"
    grandchild_pid = int(pidfile.read_text().strip())

    # With the fix, killpg tears down the group; the grandchild is SIGKILLed and
    # reaped by init. Without the fix it is orphaned and stays alive for 300s.
    deadline = time.monotonic() + 5.0
    while _pid_alive(grandchild_pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    if _pid_alive(grandchild_pid):
        # Clean up the orphan we just proved exists, then fail loudly.
        with __import__("contextlib").suppress(ProcessLookupError, OSError):
            os.kill(grandchild_pid, 9)
        pytest.fail(
            f"grandchild {grandchild_pid} survived run_simple timeout — "
            "the process group was not reaped (orphaned grandchild)"
        )

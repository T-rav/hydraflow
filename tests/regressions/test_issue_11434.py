"""Regression pins for #11434: quality_host_lock.py must not outlive its parent.

DiagnosticLoop kills `make` and destroys the worktree at attempt end, but the
`uv run` -> quality_host_lock.py layer underneath used to survive, get
reparented to PID 1, and keep queueing for (or holding) the host lock from a
directory that no longer existed. Twelve of these piled up in one #11434
incident because SIGTERM does not reach them (the `uv run` wrapper ignores
it) and the lock itself worked correctly, so arrivals queued rather than
raced — unbounded rather than merely wasteful.

The fix is wrapper-side and self-contained: record ``os.getppid()`` once at
startup and abandon the moment it changes — leaving the queue if still
waiting, or SIGKILLing the running suite's whole process group (so
xdist workers can't survive as the new orphans) if already running.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - exercises the wrapper script itself
import sys
import time
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quality_host_lock.py"


def _launch_orphaned(
    tmp_path: Path, command: list[str], env: dict[str, str] | None = None
) -> Path:
    """Run *command* under quality_host_lock.py, then orphan the wrapper.

    A "launcher" process Popen's the wrapper (capturing its stdout/stderr
    to a log file so the test can inspect it after the launcher is gone),
    then sleeps briefly before exiting — reparenting the wrapper the same
    way DiagnosticLoop killing `make` left the wrapper underneath it alive
    (#11434). The sleep matters: without it the launcher can exit before
    the wrapper has even finished interpreter startup, so the wrapper's
    *first* ``os.getppid()`` read (the one it records as "home") already
    observes the post-orphan value and no change is ever seen. Returns the
    log file path; the log is flushed to disk by the wrapper itself
    regardless of whether the orphan has been reaped yet, so reading it
    never races on pid liveness/zombie semantics.
    """
    log_path = tmp_path / "wrapper.log"
    full_env = {**os.environ, **(env or {})}
    launcher = (
        "import os, subprocess, sys, time\n"
        f"log = open({str(log_path)!r}, 'w')\n"
        "subprocess.Popen(\n"
        f"    [sys.executable, {str(_SCRIPT)!r}, '--', *{command!r}],\n"
        "    stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy(),\n"
        ")\n"
        "time.sleep(1.0)\n"
    )
    subprocess.run(  # nosec B603
        [sys.executable, "-c", launcher], env=full_env, check=True, timeout=15
    )
    return log_path


def _wait_for(predicate, timeout: float, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_abandons_while_queueing_when_parent_dies(tmp_path: Path) -> None:
    """Orphaned during the wait: must leave the queue, never run the suite."""
    env = {"TMPDIR": str(tmp_path)}
    holder = subprocess.Popen(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", "sleep", "8"],
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.8)  # let the holder acquire the lock first

    marker = tmp_path / "ran.marker"
    command = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"]
    log_path = _launch_orphaned(tmp_path, command, env=env)

    try:
        assert _wait_for(
            lambda: (
                "leaving the queue" in log_path.read_text().lower()
                if log_path.exists()
                else False
            ),
            timeout=10,
        ), log_path.read_text() if log_path.exists() else "<no log>"
        assert not marker.exists(), (
            "wrapper ran the queued command after its parent died instead "
            "of leaving the queue"
        )
    finally:
        holder.wait(timeout=30)


def test_kills_whole_process_group_when_parent_dies_while_running(
    tmp_path: Path,
) -> None:
    """Orphaned mid-run: the suite's ENTIRE tree (incl. grandchildren) dies."""
    env = {"TMPDIR": str(tmp_path)}
    heartbeat = tmp_path / "heartbeat.txt"
    # "make" stand-in: spawns its own child (an xdist-worker stand-in) that
    # heartbeats to a file, proving whether the whole group was reaped
    # rather than just the direct child.
    worker_src = (
        "import time\n"
        "i = 0\n"
        "while True:\n"
        f"    open({str(heartbeat)!r}, 'a').write(str(i) + chr(10))\n"
        "    i += 1\n"
        "    time.sleep(0.2)\n"
    )
    make_src = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {worker_src!r}])\n"
        "time.sleep(60)\n"
    )
    command = [sys.executable, "-c", make_src]

    log_path = _launch_orphaned(tmp_path, command, env=env)

    assert _wait_for(lambda: heartbeat.exists(), timeout=8), "suite tree never started"
    count_at_orphan = len(heartbeat.read_text().splitlines())

    # Give the wrapper's poll loop (2s cadence) time to notice and reap.
    assert _wait_for(
        lambda: (
            "abandon" in log_path.read_text().lower() if log_path.exists() else False
        ),
        timeout=10,
    ), log_path.read_text() if log_path.exists() else "<no log>"

    count_after_kill = len(heartbeat.read_text().splitlines())
    time.sleep(1.0)
    count_settled = len(heartbeat.read_text().splitlines())

    assert count_after_kill < count_at_orphan + 20, (
        "heartbeat kept growing well past the abandonment message — the "
        "worker (grandchild) tree was not actually killed"
    )
    assert count_settled == count_after_kill, (
        "heartbeat resumed growing after the kill — process group survived"
    )


def test_forwards_sigterm_to_the_running_process_group(tmp_path: Path) -> None:
    """A direct SIGTERM to the wrapper must reach the whole suite tree too.

    ``start_new_session=True`` takes the suite out of the terminal's
    foreground process group, so without explicit forwarding SIGTERM would
    stop the wrapper but leave the suite running — the exact "SIGTERM does
    not clear them" complaint from #11434.
    """
    env = {"TMPDIR": str(tmp_path)}
    heartbeat = tmp_path / "heartbeat.txt"
    worker_src = (
        "import time\n"
        "i = 0\n"
        "while True:\n"
        f"    open({str(heartbeat)!r}, 'a').write(str(i) + chr(10))\n"
        "    i += 1\n"
        "    time.sleep(0.2)\n"
    )
    make_src = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {worker_src!r}])\n"
        "time.sleep(60)\n"
    )
    command = [sys.executable, "-c", make_src]

    wrapper = subprocess.Popen(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", *command],
        env={**os.environ, **env},
    )
    try:
        assert _wait_for(lambda: heartbeat.exists(), timeout=8), (
            "suite tree never started"
        )
        count_before = len(heartbeat.read_text().splitlines())

        wrapper.send_signal(15)  # SIGTERM
        wrapper.wait(timeout=10)
        assert wrapper.returncode == 128 + 15

        time.sleep(0.6)
        count_after = len(heartbeat.read_text().splitlines())
        time.sleep(1.0)
        count_settled = len(heartbeat.read_text().splitlines())

        assert count_settled == count_after, (
            "heartbeat kept growing after SIGTERM — the worker (grandchild) "
            "survived even though the wrapper itself exited"
        )
        assert count_after < count_before + 20
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=10)


def test_acquire_abandons_when_ppid_diverges_to_a_non_one_value(
    tmp_path: Path, monkeypatch
) -> None:
    """Must compare against the recorded parent pid, never a literal `1`.

    Under a subreaper an orphan is reparented onto the subreaper's pid, not
    onto PID 1 — a `os.getppid() == 1` check would silently never fire.
    """
    from scripts.quality_host_lock import _acquire

    handle = (tmp_path / "lock").open("w")
    recorded_parent_pid = os.getppid()
    monkeypatch.setattr(os, "getppid", lambda: recorded_parent_pid + 1)
    try:
        state = _acquire(handle, timeout_s=30, parent_pid=recorded_parent_pid)
        assert state == "abandoned"
    finally:
        handle.close()


def test_acquire_does_not_abandon_when_recorded_parent_pid_is_one(
    tmp_path: Path, monkeypatch
) -> None:
    """A live ppid of 1 that MATCHES the recorded parent must not abandon.

    Guards against overcorrecting into a `ppid == 1` check pointed the
    wrong way — the comparison must be against the recorded value, so an
    unchanged ppid of 1 (wrapper's real parent legitimately is init) still
    proceeds to acquire the free lock normally.
    """
    from scripts.quality_host_lock import _acquire

    handle = (tmp_path / "lock").open("w")
    monkeypatch.setattr(os, "getppid", lambda: 1)
    try:
        state = _acquire(handle, timeout_s=30, parent_pid=1)
        assert state == "acquired"
    finally:
        handle.close()


def test_normal_run_still_propagates_exit_code_when_parent_stays_alive(
    tmp_path: Path,
) -> None:
    """Counter-pin: the parent-liveness guard must not disturb the happy path."""
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    result = subprocess.run(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", "sh", "-c", "exit 5"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 5

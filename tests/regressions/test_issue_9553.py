"""Regression: watchdog-cancelled loop cycles must leave ZERO orphaned OS
processes — the end-to-end integration guarantee over the reap family (#9553).

The reap primitives were built and pinned per-site across #9641 (single
``kill_process_group`` guard), #9911/#9983/#10019 (runtime-wide tracked
registry + ``run_simple`` group-leader spawns), #10002 (stop-path drains) and
#9800 (streaming sites). Each of those pins ONE site. Nothing asserted the
whole chain a real watchdog fires:

    BaseBackgroundLoop._execute_cycle watchdog overrun
      -> LoopCycleTimeoutError
      -> work_task.cancel()
      -> CancelledError unwinds into _do_work
      -> into the awaited subprocess spawn path
      -> kill_process_group(pgid) tears down the WHOLE process group

This file drives that chain with a REAL BaseBackgroundLoop subclass whose
``_do_work`` spawns a real process tree (a bash leader with a ``sleep``
grandchild in the same process group via ``start_new_session``) and then
blocks, forcing the real per-cycle watchdog (:meth:`_cycle_timeout_seconds`
overridden tiny) to cancel it. It proves the GRANDCHILD dies — a leader-only
``proc.kill()`` would spare it — for BOTH spawn paths a loop cycle can park on:

- the bounded-subprocess path (``HostRunner.run_simple`` CancelledError reap), and
- the streaming path (``stream_claude_process`` CancelledError reap).

and that the tracked registry / loop-owned ``active_procs`` are left clean (no
leaked handles to accumulate over a long-running factory). Mocks are avoided in
the reap path entirely: a fabricated ``.pid`` coerces to 1 and ``os.killpg(1,
SIGKILL)`` is catastrophic (the #9641 / #9983 hazard), so only real children,
with real pids, are ever signalled here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import process_group
from base_background_loop import BaseBackgroundLoop
from models import WorkCycleResult
from tests.helpers import make_bg_loop_deps

# The per-cycle watchdog bound the probe loop runs under. Tiny so the test is
# fast, but comfortably larger than the ~milliseconds bash needs to fork the
# grandchild and write its pid — the spawn always wins the race to disk before
# the watchdog cancels the cycle.
_WATCHDOG_SECONDS = 1

# Bounds for the whole cycle drive and for the post-reap death poll. Generous
# so a loaded CI runner does not flake, but finite so a real reap REGRESSION
# fails loudly instead of wedging the suite.
_CYCLE_DRIVE_TIMEOUT = 30.0
_DEATH_POLL_SECONDS = 5.0

# bash keeps the group leader and its backgrounded ``sleep`` grandchild in one
# process group (the loop spawns it with start_new_session=True), and ``wait``
# blocks the leader forever so the cycle parks until the watchdog cancels it.
_TREE_SCRIPT = "sleep 300 & echo $! > {pidfile}; wait"


def _pid_alive(pid: int) -> bool:
    """True if *pid* still names a live process (POSIX signal-0 probe)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_grandchild_pid(pidfile: Path) -> int:
    """Read the grandchild pid the tree wrote, asserting it was ever spawned."""
    deadline = time.monotonic() + _DEATH_POLL_SECONDS
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pidfile.exists(), "tree never spawned its grandchild (no pidfile)"
    pid = int(pidfile.read_text().strip())
    assert pid > 0
    return pid


def _await_dead(pid: int) -> None:
    """Poll until *pid* is gone, bounded — a survivor means the group leaked."""
    deadline = time.monotonic() + _DEATH_POLL_SECONDS
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)


class _ProcessTreeProbeLoop(BaseBackgroundLoop):
    """A real background loop whose one cycle spawns a real process tree and
    then blocks, so the real watchdog must cancel it.

    ``mode`` selects which spawn path the cycle parks on — the two paths a
    cancelled cycle can unwind through — so a single loop proves both.
    """

    def __init__(self, *, mode: str, pidfile: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._mode = mode
        self._pidfile = pidfile
        # Streaming path's caller-owned set; asserted empty after the reap.
        self._active_procs: set[asyncio.subprocess.Process] = set()

    def _cycle_timeout_seconds(self) -> int:
        return _WATCHDOG_SECONDS

    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self) -> WorkCycleResult:
        script = _TREE_SCRIPT.format(pidfile=self._pidfile)
        if self._mode == "run_simple":
            from execution import HostRunner

            # Bounded-subprocess path: run_simple spawns a group leader,
            # registers it in the reap registry, and on CancelledError group-
            # kills it (#9911/#9983). timeout huge so the WATCHDOG cancels first.
            await HostRunner().run_simple(["bash", "-c", script], timeout=300.0)
        else:
            from runner_utils import StreamConfig, stream_claude_process

            # Streaming path: stream_claude_process parks on proc.stdout until
            # the cycle is cancelled, then group-kills on CancelledError (#9800).
            # timeout huge so the watchdog's cancel — not the stream's own
            # wait_for — is what fires.
            await stream_claude_process(
                cmd=["bash", "-c", script],
                prompt="",
                cwd=Path.cwd(),
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data={"issue": 9553, "source": "test_9553"},
                logger=logging.getLogger("test_9553"),
                config=StreamConfig(timeout=300.0),
            )
        return None


def _make_probe_loop(
    tmp_path: Path, *, mode: str, pidfile: Path
) -> _ProcessTreeProbeLoop:
    deps = make_bg_loop_deps(tmp_path)
    return _ProcessTreeProbeLoop(
        mode=mode,
        pidfile=pidfile,
        worker_name="reap_probe",
        config=deps.config,
        deps=deps.loop_deps,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups only")
class TestWatchdogCancelReapsProcessTree:
    """A watchdog-cancelled cycle reaps the whole OS process group — leader AND
    grandchild — and leaves the tracked registry clean, for both spawn paths."""

    async def _drive_and_assert(self, tmp_path: Path, mode: str) -> None:
        before = set(process_group._TRACKED)
        pidfile = tmp_path / "grandchild.pid"
        loop = _make_probe_loop(tmp_path, mode=mode, pidfile=pidfile)
        grandchild: int | None = None
        try:
            # Drive exactly one cycle. The watchdog overruns at
            # _WATCHDOG_SECONDS, cancels _do_work, and the cancel unwinds into
            # the spawn path's reap. Bounded so a reap regression fails loudly.
            await asyncio.wait_for(loop._execute_cycle(), timeout=_CYCLE_DRIVE_TIMEOUT)

            grandchild = _read_grandchild_pid(pidfile)
            _await_dead(grandchild)

            assert not _pid_alive(grandchild), (
                f"{mode}: grandchild {grandchild} survived the watchdog cancel "
                "— the cycle reaped only the leader, not the process group"
            )
            # The spawn path deregistered on the way out (no leaked handles).
            assert loop._active_procs == set()
            assert set(process_group._TRACKED) <= before
        finally:
            if grandchild is not None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.kill(grandchild, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_bounded_subprocess_path_reaps_tree(self, tmp_path: Path) -> None:
        """run_simple's CancelledError reap tears down the whole group when the
        watchdog cancels a cycle blocked on a bounded subprocess."""
        await self._drive_and_assert(tmp_path, "run_simple")

    @pytest.mark.asyncio
    async def test_streaming_path_reaps_tree(self, tmp_path: Path) -> None:
        """stream_claude_process's CancelledError reap tears down the whole
        group when the watchdog cancels a cycle blocked streaming an agent."""
        await self._drive_and_assert(tmp_path, "stream")

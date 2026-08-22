"""Regression: stop/shutdown path orphaned in-flight subprocesses (#9911).

After "Stop requested — terminating active processes" the runtime reported
idle, yet a full pytest run spawned by a loop cycle was still alive 22
minutes later (PID 11989, PPID=1, ELAPSED 52:11) — reparented to launchd,
its result unconsumable. The stop path terminated only the four
runner-owned ``_active_procs`` sets; acceptance_criteria,
verification_judge and report_issue_loop children (owners that have no
``terminate()`` at all) were never reaped, and three
kill sites used plain ``proc.kill()`` which leaks the process GROUP.

Pins:
- ``_ALL_TRACKED_PROCS``: every ``stream_claude_process`` spawn registers
  and deregisters, regardless of which owner's set was passed in.
- ``reap_all_tracked_processes`` SIGKILLs the whole group of live tracked
  children (real-subprocess grandchild test — mocks cannot prove a group
  died) and skips already-exited ones.
- The timeout / cancel / on_output-early-kill sites group-kill.
- ``orchestrator.stop()``, ``_supervise_loops``'s finally drain, and
  ``_cancel_all_loops_and_runners`` all invoke the shared reaper.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import runner_utils
from orchestrator import HydraFlowOrchestrator
from runner_utils import reap_all_tracked_processes

# `make quality` runs this file's serial job alongside pyright, bandit, the
# full -n auto suite, and (on the shared dark-factory box) other worktrees'
# quality gates at once; a real spawn/reap can take far longer than the 5s
# these polls used to allow, flaking the assertion rather than the process
# itself (confirmed: this file's runtime went 7s standalone -> 300s+ under
# realistic concurrent load).
_POLL_DEADLINE_S = 30


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _FakeProc:
    """Minimal proc fake — MUST expose .pid (the #9983 _DeadProc lesson:
    killpg-based reapers touch .pid, and AttributeError is not caught by
    the ProcessLookupError/OSError suppression)."""

    def __init__(self, pid: int = 424242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.killed = False

    def kill(self) -> None:
        self.killed = True


class TestReapAllTrackedProcesses:
    def test_real_process_group_is_torn_down(self, tmp_path: Path) -> None:
        """A tracked child's GRANDCHILD dies too — group kill, not child kill."""
        pidfile = tmp_path / "grandchild.pid"
        proc = subprocess.Popen(
            ["bash", "-c", f"sleep 300 & echo $! > {pidfile}; wait"],
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + _POLL_DEADLINE_S
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            grandchild = int(pidfile.read_text().strip())
            assert _pid_alive(grandchild)

            fake = _FakeProc(pid=proc.pid, returncode=None)
            runner_utils._ALL_TRACKED_PROCS.add(fake)  # type: ignore[arg-type]

            reaped = reap_all_tracked_processes()

            assert reaped == 1
            deadline = time.monotonic() + _POLL_DEADLINE_S
            while _pid_alive(grandchild) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _pid_alive(grandchild), "grandchild survived the group kill"
            assert not runner_utils._ALL_TRACKED_PROCS
        finally:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    def test_already_exited_children_are_skipped(self) -> None:
        exited = _FakeProc(pid=111, returncode=0)
        runner_utils._ALL_TRACKED_PROCS.add(exited)  # type: ignore[arg-type]

        with patch("process_group.os.killpg") as killpg:
            reaped = reap_all_tracked_processes()

        assert reaped == 0
        killpg.assert_not_called()
        assert not runner_utils._ALL_TRACKED_PROCS

    def test_live_children_group_killed_via_killpg(self) -> None:
        live = _FakeProc(pid=424242, returncode=None)
        runner_utils._ALL_TRACKED_PROCS.add(live)  # type: ignore[arg-type]

        with patch("process_group.os.killpg") as killpg:
            reaped = reap_all_tracked_processes()

        assert reaped == 1
        killpg.assert_called_once_with(424242, signal.SIGKILL)
        assert live.killed is False  # group kill, not the child-only fallback


class TestStreamRegistersEverySpawn:
    @pytest.mark.asyncio
    async def test_spawn_registers_and_finally_deregisters(self) -> None:
        """The runtime-wide registry sees the proc while running, not after."""
        from runner_utils import StreamConfig, stream_claude_process

        seen_during: list[bool] = []

        class _Recorder:
            async def run_simple(self, *args, **kwargs):  # pragma: no cover
                raise NotImplementedError

            async def cleanup(self) -> None:  # protocol conformance
                return None

            async def create_streaming_process(self, *args, **kwargs):
                proc = MagicMock()
                proc.pid = 777
                proc.returncode = 0

                async def _aiter():
                    seen_during.append(proc in runner_utils._ALL_TRACKED_PROCS)
                    return
                    yield  # pragma: no cover

                proc.stdout = _aiter()
                proc.stderr = MagicMock()
                proc.stderr.read = AsyncMock(return_value=b"")
                proc.wait = AsyncMock(return_value=0)
                return proc

        await stream_claude_process(
            cmd=["claude", "-p"],
            prompt="x",
            cwd=Path.cwd(),
            active_procs=set(),
            event_bus=MagicMock(publish=AsyncMock()),
            event_data={"issue": 1, "source": "test"},
            logger=MagicMock(),
            config=StreamConfig(runner=_Recorder(), timeout=5),
        )

        assert seen_during == [True]
        assert not runner_utils._ALL_TRACKED_PROCS


class TestOrchestratorHooksInvokeReaper:
    def _orch(self, config) -> HydraFlowOrchestrator:
        orch = HydraFlowOrchestrator(config)
        orch._svc = MagicMock()
        orch._state = MagicMock()
        orch._loop_tasks = {}
        return orch

    @pytest.mark.asyncio
    async def test_stop_reaps_tracked_registry(self, config) -> None:
        orch = self._orch(config)
        with (
            patch.object(orch, "_build_interrupted_issues", AsyncMock(return_value=[])),
            patch("orchestrator_lifecycle.reap_all_tracked_processes", return_value=2) as reap,
        ):
            await orch.stop()

        reap.assert_called_once()
        orch._svc.planners.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_all_loops_and_runners_reaps(self, config) -> None:
        orch = self._orch(config)

        async def _noop() -> None:
            await asyncio.sleep(0)

        task = asyncio.create_task(_noop())
        with patch("orchestrator_credits.reap_all_tracked_processes") as reap:
            await orch._cancel_all_loops_and_runners({"x": task})

        reap.assert_called_once()


class TestRunSimpleChildrenAreStopReapable:
    """#9911 follow-up: run_simple children register in the shared registry,
    so a stop/shutdown mid-flight reaps them — previously only run_simple's
    own timeout could, and a Stop during a long make/pytest left the tree
    running at PPID=1."""

    @pytest.mark.asyncio
    async def test_in_flight_run_simple_child_is_reaped_by_stop_path(
        self, tmp_path: Path
    ) -> None:
        import process_group
        from execution import HostRunner

        pidfile = tmp_path / "grandchild.pid"
        runner_task = asyncio.create_task(
            HostRunner().run_simple(
                ["bash", "-c", f"sleep 300 & echo $! > {pidfile}; wait"],
                timeout=60,
            )
        )
        try:
            deadline = time.monotonic() + _POLL_DEADLINE_S
            while not pidfile.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            grandchild = int(pidfile.read_text().strip())
            assert _pid_alive(grandchild)

            reaped = reap_all_tracked_processes()

            assert reaped >= 1
            deadline = time.monotonic() + _POLL_DEADLINE_S
            while _pid_alive(grandchild) and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert not _pid_alive(grandchild), (
                "run_simple grandchild survived the stop-path reap"
            )
        finally:
            runner_task.cancel()
            await asyncio.gather(runner_task, return_exceptions=True)
            assert not process_group._TRACKED

    @pytest.mark.asyncio
    async def test_completed_run_simple_child_is_deregistered(self) -> None:
        import process_group
        from execution import HostRunner

        await HostRunner().run_simple(["true"], timeout=10)

        assert not process_group._TRACKED

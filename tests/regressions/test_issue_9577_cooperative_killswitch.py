"""Regression: the shared subprocess helper learns cooperative cancellation (#9577).

Before this, a long local subprocess (a 45-min `git bisect run`) could only
be stopped by its timeout — a loop's mid-run kill-switch toggle was ignored
until completion. #10060 had to EXCLUDE staging_bisect._run_git from the
shared-helper migration for exactly this reason. Now HostRunner.run_simple
takes a `cancel_check` polled every `cancel_poll_interval` seconds; a True
verdict tears down the whole process group and raises
SubprocessCancelledError, so staging_bisect._run_git migrates onto the
shared helper and drops its bespoke poll loop.

Pins:
- No cancel_check → run_simple behaves exactly as before (plain wait_for).
- cancel_check that flips True mid-run → the REAL running child's group is
  killed (grandchild dies too) and SubprocessCancelledError is raised.
- A cancel_check that never trips → normal completion, no false cancel.
- staging_bisect._run_git maps SubprocessCancelledError → BisectCancelledError.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from execution import HostRunner, SubprocessCancelledError


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class TestRunSimpleCooperativeCancel:
    @pytest.mark.asyncio
    async def test_no_cancel_check_is_unchanged(self) -> None:
        result = await HostRunner().run_simple(["echo", "hi"], timeout=10)
        assert result.returncode == 0
        assert result.stdout == "hi"

    @pytest.mark.asyncio
    async def test_never_tripping_check_completes_normally(self) -> None:
        result = await HostRunner().run_simple(
            ["echo", "ok"],
            timeout=10,
            cancel_check=lambda: False,
            cancel_poll_interval=0.05,
        )
        assert result.returncode == 0
        assert result.stdout == "ok"

    @pytest.mark.asyncio
    async def test_tripped_check_group_kills_and_raises(self, tmp_path: Path) -> None:
        """A real forking child + backgrounded grandchild are both reaped."""
        pidfile = tmp_path / "grandchild.pid"
        # sh backgrounds a 300s sleep (the grandchild), records its pid, waits.
        cmd = ["sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait"]

        flip = {"cancel": False}

        async def _flip_soon() -> None:
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            flip["cancel"] = True

        flipper = asyncio.create_task(_flip_soon())
        with pytest.raises(SubprocessCancelledError):
            await HostRunner().run_simple(
                cmd,
                timeout=30,
                cancel_check=lambda: flip["cancel"],
                cancel_poll_interval=0.1,
            )
        await flipper

        grandchild = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 5
        while _pid_alive(grandchild) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not _pid_alive(grandchild), "grandchild survived the group cancel"

    @pytest.mark.asyncio
    async def test_cancel_beats_a_generous_timeout(self) -> None:
        """The cancel path fires well before the (large) timeout would."""
        started = time.monotonic()
        with pytest.raises(SubprocessCancelledError):
            await HostRunner().run_simple(
                ["sleep", "300"],
                timeout=300,
                cancel_check=lambda: True,  # trip on the first poll
                cancel_poll_interval=0.1,
            )
        assert time.monotonic() - started < 10


class TestStagingBisectUsesTheHook:
    @pytest.mark.asyncio
    async def test_run_git_maps_cancel_to_bisect_cancelled(
        self, tmp_path: Path
    ) -> None:
        from staging_bisect_loop import BisectCancelledError, StagingBisectLoop

        loop = StagingBisectLoop.__new__(StagingBisectLoop)
        # Kill-switch already off → cancel_check returns True on first poll.
        object.__setattr__(loop, "_worker_name", "staging_bisect")
        object.__setattr__(loop, "_enabled_cb", lambda _name: False)

        with pytest.raises(BisectCancelledError):
            await loop._run_git(["sleep", "300"], cwd=tmp_path, timeout=300)

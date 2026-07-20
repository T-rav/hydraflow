"""Regression (#9624): ``FakeSubprocessRunner._run_on_host`` must share
``HostRunner.run_simple``'s exact host-process lifecycle.

The fake used to be a *near-duplicate* of the real runner that had silently
diverged from the hardened reap semantics (#9648/#9911): it spawned WITHOUT
``start_new_session=True``, reaped only the direct child (``proc.kill()``) on
``TimeoutError``, and had NO ``asyncio.CancelledError`` handler at all. So a
forking host command routed through it — or a cancelled cycle — orphaned the
grandchildren (sub-make, pytest workers, backgrounded processes) that the real
``HostRunner`` reaps as a whole process group. That is a fake-fidelity defect:
scenarios passed against a lifecycle production never exhibits.

The fix delegates ``_run_on_host`` to ``HostRunner.run_simple`` so the two host
paths cannot diverge again. Every test below is parametrized over BOTH entry
points — that parametrization IS the parity contract: any divergence fails one
leg.

Two layers, per the documented process-group reap-test strategy:

1. mock-unit — patch ``process_group.os.killpg`` + ``asyncio.create_subprocess_exec``
   (concrete int pid, never a bare ``MagicMock`` pid) and assert the group
   reap fires on both timeout and cancel, plus ``start_new_session=True`` at
   spawn and unchanged happy-path output.
2. real-subprocess — spawn a genuine forking ``sh`` group, time it out / cancel
   it, and prove the OS actually reaped the backgrounded grandchild. Only a
   real spawned group can prove the kernel tore the tree down; mocks only prove
   the call was issued.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution import HostRunner, SimpleResult
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner


# The two host-exec entry points that MUST behave identically. Running every
# assertion against both is how this file pins parity: the real runner is the
# reference, the fake must match it byte-for-byte in lifecycle.
async def _via_host_runner(
    cmd: Sequence[str], *, timeout: float = 120.0, cwd: str | None = None
) -> SimpleResult:
    return await HostRunner().run_simple(cmd, timeout=timeout, cwd=cwd)


async def _via_fake_host(
    cmd: Sequence[str], *, timeout: float = 120.0, cwd: str | None = None
) -> SimpleResult:
    return await FakeSubprocessRunner._run_on_host(cmd, timeout=timeout, cwd=cwd)


_RUN_HOST = pytest.mark.parametrize(
    "run_host",
    [_via_host_runner, _via_fake_host],
    ids=["HostRunner.run_simple", "FakeSubprocessRunner._run_on_host"],
)


# --------------------------------------------------------------------------- #
# Layer 1 — mock-unit parity
# --------------------------------------------------------------------------- #


@_RUN_HOST
@pytest.mark.asyncio
async def test_host_path_spawns_start_new_session_and_preserves_output(
    run_host,
) -> None:
    """Both host paths spawn a session leader and return identical output."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await run_host(["echo", "hi"])

    _, kwargs = mock_create.call_args
    assert kwargs["start_new_session"] is True
    # Happy-path shape is unchanged by the parity fix.
    assert result == SimpleResult(stdout="ok", stderr="", returncode=0)


@_RUN_HOST
@pytest.mark.asyncio
async def test_host_path_reaps_whole_group_on_timeout(run_host) -> None:
    """On timeout the WHOLE process group is SIGKILLed via ``os.killpg`` — not
    just the direct child — and the ``TimeoutError`` still propagates."""
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        patch("process_group.os.killpg") as mock_killpg,
        pytest.raises(TimeoutError),
    ):
        await run_host(["sleep", "999"], timeout=0.01)

    mock_killpg.assert_called_once_with(4242, signal.SIGKILL)
    # The group kill covers the child; the direct-child-only kill must NOT fire.
    mock_proc.kill.assert_not_called()


@_RUN_HOST
@pytest.mark.asyncio
async def test_host_path_reaps_whole_group_on_cancel(run_host) -> None:
    """External cancellation (a loop watchdog / kill-switch) reaps the whole
    group too and re-raises ``CancelledError``.

    This is the divergence #9624 names: the fake previously had no
    ``CancelledError`` handler, so cancelling it orphaned the child + group
    while the real runner reaped it. Parity requires the killpg on this leg.
    """
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        patch("process_group.os.killpg") as mock_killpg,
        pytest.raises(asyncio.CancelledError),
    ):
        await run_host(["sleep", "999"], timeout=999)

    mock_killpg.assert_called_once_with(4242, signal.SIGKILL)
    mock_proc.kill.assert_not_called()


# --------------------------------------------------------------------------- #
# Layer 2 — real-subprocess group reap
# --------------------------------------------------------------------------- #


def _pid_alive(pid: int) -> bool:
    """True while *pid* still names a live-or-zombie process we can signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # pid was recycled to a process we don't own — treat as gone.
        return False
    return True


async def _wait_pid_gone(pid: int, timeout: float = 5.0) -> bool:
    """Poll until *pid* is fully gone (SIGKILLed group members become zombies
    briefly before the subreaper reaps them). Bounded so a leak still fails."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(0.02)
    return not _pid_alive(pid)


def _forking_cmd(pidfile: os.PathLike[str]) -> list[str]:
    """A host command that backgrounds a long-lived grandchild and records its
    pid. ``start_new_session=True`` makes the shell a group leader, so a group
    SIGKILL must reap the backgrounded ``sleep`` too — not just the shell."""
    return ["sh", "-c", f"sleep 30 & echo $! > {pidfile}; wait"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@_RUN_HOST
@pytest.mark.asyncio
async def test_forking_host_command_reaped_on_timeout(run_host, tmp_path) -> None:
    pidfile = tmp_path / "gc.pid"
    with pytest.raises(TimeoutError):
        await run_host(_forking_cmd(pidfile), timeout=0.5)

    grandchild = int(pidfile.read_text().strip())
    assert await _wait_pid_gone(grandchild), (
        f"grandchild {grandchild} survived the timeout reap — the host path "
        "did not tear down the whole process group"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@_RUN_HOST
@pytest.mark.asyncio
async def test_forking_host_command_reaped_on_cancel(run_host, tmp_path) -> None:
    pidfile = tmp_path / "gc.pid"
    task = asyncio.create_task(run_host(_forking_cmd(pidfile), timeout=120))

    # Wait until the shell has forked the grandchild and recorded its pid.
    for _ in range(250):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.02)
    grandchild = int(pidfile.read_text().strip())
    assert _pid_alive(grandchild)  # sanity: it is running before we cancel

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _wait_pid_gone(grandchild), (
        f"grandchild {grandchild} survived cancellation — the host path "
        "orphaned the process group instead of reaping it (the #9624 divergence)"
    )

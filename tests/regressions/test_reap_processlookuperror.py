"""Regression: a timed-out subprocess whose child already exited must surface
``TimeoutError`` (the intended failed-read signal), NOT ``ProcessLookupError``
from ``proc.kill()``.

Root cause (observed live: a gh-timeout storm crashed ~6 loops + the HITL
close/requeue actions): on timeout the reap calls ``proc.kill()``; if the
child already exited, ``proc.kill()`` raises ``ProcessLookupError``. In the
loop ``_communicate_bounded`` helpers the ``contextlib.suppress`` wrapped only
``proc.wait()`` (not ``proc.kill()``), and ``execution.run_simple`` had no
suppress at all — so the ``ProcessLookupError`` escaped and crashed the loop
iteration instead of the caller handling the timeout. See #9794 / #9814.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class _DeadProc:
    """Hangs on communicate() (so wait_for times out) and models an already-dead
    child: proc.kill() raises ProcessLookupError, like a real reaped child. A
    real asyncio Process always exposes a ``pid`` (used by the #9648 killpg reap
    path in execution.run_simple); the tests that exercise killpg model the
    process group as already-gone by patching os.killpg to raise."""

    returncode: int | None = None
    pid: int = 424242

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        await asyncio.sleep(5)  # longer than the patched timeout
        return (b"", b"")

    def kill(self) -> None:
        raise ProcessLookupError()  # child already exited

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name,timeout_attr",
    [
        ("flake_tracker_loop", "_GH_TIMEOUT_SECONDS"),
        ("rc_budget_loop", "_GH_TIMEOUT_SECONDS"),
        ("fake_coverage_auditor_loop", "_SUBPROCESS_TIMEOUT_SECONDS"),
        ("adr_touchpoint_auditor_loop", "_GH_TIMEOUT_SECONDS"),
    ],
)
async def test_communicate_bounded_surfaces_timeout_not_processlookup(
    monkeypatch, module_name, timeout_attr
):
    module = __import__(module_name)
    monkeypatch.setattr(module, timeout_attr, 0.01)
    # Must raise TimeoutError (caller treats as failed read), never the
    # ProcessLookupError from the already-dead child's proc.kill().
    with pytest.raises(TimeoutError):
        await module._communicate_bounded(_DeadProc())


@pytest.mark.asyncio
async def test_host_runner_run_simple_surfaces_timeout_not_processlookup(monkeypatch):
    import execution

    async def _fake_create(*_a, **_kw):
        return _DeadProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    # #9648 changed the reap to os.killpg(proc.pid, SIGKILL). Model the process
    # group as already-gone so killpg raises ProcessLookupError, exactly like a
    # real reaped child. run_simple must still surface TimeoutError (the intended
    # failed-read signal), never the ProcessLookupError from the reap (#9794/#9814).
    def _dead_killpg(_pgid: int, _sig: int) -> None:
        raise ProcessLookupError()

    # execution.run_simple calls os.killpg on the shared os module, so patching
    # it here also patches the call inside run_simple.
    monkeypatch.setattr(os, "killpg", _dead_killpg)
    runner = execution.HostRunner()
    with pytest.raises(TimeoutError):
        await runner.run_simple(["gh", "issue", "list"], timeout=0.01)

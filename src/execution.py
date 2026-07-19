"""Subprocess execution abstraction — host vs Docker."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SimpleResult:
    """Result from a simple (non-streaming) subprocess execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@runtime_checkable
class SubprocessRunner(Protocol):
    """Protocol for executing subprocesses.

    Two implementations:
    - ``HostRunner``: executes on the host via ``asyncio.create_subprocess_exec``
    - ``DockerRunner``: executes inside a Docker container
    """

    async def create_streaming_process(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        limit: int = 1024 * 1024,
        start_new_session: bool = True,
    ) -> asyncio.subprocess.Process:
        """Create a subprocess with stdin/stdout/stderr pipes for streaming.

        The caller is responsible for writing to stdin, reading stdout,
        draining stderr, and managing the process lifecycle.
        """
        ...

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        """Run a command and return its output.

        When *input* is provided, it is written to the process's stdin.

        Raises ``TimeoutError`` if the command exceeds *timeout* seconds
        (the process is killed before re-raising).

        Raises ``FileNotFoundError`` if the executable is not found on the host.
        """
        ...

    async def cleanup(self) -> None:
        """Clean up any resources (containers, connections, etc.)."""
        ...


def _reap_process_group(proc: asyncio.subprocess.Process) -> None:
    """Best-effort SIGKILL of *proc*'s whole process group.

    A real asyncio child spawned with ``start_new_session=True`` is its own
    process-group leader (``pid == pgid``), so ``os.killpg(proc.pid, SIGKILL)``
    tears down the child AND the grandchildren it forked (sub-make / pytest /
    agent workers) — the orphaned-grandchild defect from #9648 (mirrors
    ``terminate_processes()`` and the #9579 caretaker fix).

    The kill is guarded on an *integer* pid. A real child always has one; a
    missing or non-int pid (a not-yet-started process, or a test double whose
    ``pid`` is a mock) falls back to ``proc.kill()`` so the reap never issues
    ``os.killpg`` against a fabricated pid — an int-coerced mock resolves to a
    low number like ``1`` and would otherwise signal an unrelated, or even our
    own, process group. ``ProcessLookupError``/``OSError`` (the group already
    exited) are suppressed so the caller's ``TimeoutError``/``CancelledError``
    still propagates. (#9648, #9794/#9814)
    """
    with contextlib.suppress(ProcessLookupError, OSError):
        if isinstance(proc.pid, int):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()


class HostRunner:
    """Execute subprocesses on the host using ``asyncio.create_subprocess_exec``."""

    async def create_streaming_process(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        limit: int = 1024 * 1024,
        start_new_session: bool = True,
    ) -> asyncio.subprocess.Process:
        """Create a streaming subprocess on the host."""
        return await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            start_new_session=start_new_session,
        )

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        """Run a command on the host and return its output.

        When *input* is provided, it is written to the process's stdin.

        Raises ``TimeoutError`` if the command exceeds *timeout* seconds.
        """
        stdin_pipe = asyncio.subprocess.PIPE if input is not None else None
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=stdin_pipe,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            # Own process group so a timeout can reap the WHOLE tree, not just
            # the direct child. This is the central runner path used broadly via
            # subprocess_util.run_subprocess; the commands it runs (sub-make,
            # pytest, agent CLIs) fork their own grandchildren. (#9648)
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=input), timeout=timeout
            )
        except TimeoutError:
            # Reap the whole process group, not just the direct child. Without
            # this, sub-make / pytest / agent grandchildren are re-parented to
            # init and keep running (burning tokens, holding file handles)
            # against an abandoned cycle — the orphaned-grandchild defect from
            # #9648. start_new_session=True above makes the child a group leader
            # so the group SIGKILL tears down the whole tree.
            _reap_process_group(proc)
            # Reap the now-signalled direct child so it does not linger as a
            # zombie. SIGKILL is uncatchable, so this returns promptly; guard it
            # in case the child was already reaped between the kill and here.
            with contextlib.suppress(ProcessLookupError, OSError):
                await proc.wait()
            raise
        except asyncio.CancelledError:
            # A cancelled cycle (e.g. a loop watchdog cancelling the task) must
            # tear down the same process group, or the child and its
            # grandchildren are orphaned — the #9648 defect on the cancellation
            # trigger rather than the timeout one. Shared reap mirrors
            # stream_claude_process's TimeoutError/cancel handling. Do not block
            # the cancellation on wait(); the child watcher reaps the SIGKILLed
            # child in the background.
            _reap_process_group(proc)
            raise
        return SimpleResult(
            stdout=stdout_bytes.decode(errors="replace").strip()
            if stdout_bytes
            else "",
            stderr=stderr_bytes.decode(errors="replace").strip()
            if stderr_bytes
            else "",
            returncode=proc.returncode if proc.returncode is not None else -1,
        )

    async def cleanup(self) -> None:
        """No-op for host runner."""


_default_runner: HostRunner | None = None


def get_default_runner() -> SubprocessRunner:
    """Return a module-level ``HostRunner`` singleton."""
    global _default_runner  # noqa: PLW0603
    if _default_runner is None:
        _default_runner = HostRunner()
    return _default_runner

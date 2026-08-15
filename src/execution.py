"""Subprocess execution abstraction — host vs Docker."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic as _monotonic
from typing import Protocol, runtime_checkable

from process_group import kill_process_group, track, untrack


class SubprocessCancelledError(Exception):
    """A cooperative ``cancel_check`` returned True mid-run (#9577).

    Raised after the process group is torn down, so callers distinguish a
    kill-switch/operator cancel from a natural timeout or exit.
    """


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
        harness_env: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        """Create a subprocess with stdin/stdout/stderr pipes for streaming.

        The caller is responsible for writing to stdin, reading stdout,
        draining stderr, and managing the process lifecycle.

        ``harness_env`` is the SANCTIONED per-spawn backend override
        (``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN``/cleared
        ``ANTHROPIC_API_KEY`` — see ``resolve_harness_env``). Unlike ``env``
        — which DockerRunner deliberately ignores for container isolation —
        every runner MUST honor ``harness_env``, or a credit-failover/
        repo-provider reroute ships a glm ``--model`` to the native
        Anthropic endpoint and dies with ``unrecognized_model`` (#11263).
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
        cancel_check: Callable[[], bool] | None = None,
        cancel_poll_interval: float = 5.0,
    ) -> SimpleResult:
        """Run a command and return its output.

        When *input* is provided, it is written to the process's stdin.
        *cancel_check* (#9577) is polled every *cancel_poll_interval* seconds;
        a True verdict tears down the process group and raises
        ``SubprocessCancelledError``.

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

    Delegates to the single guarded primitive (#9641). The guard is
    STRICTER than the earlier inline check: it also rejects ``bool`` and
    non-positive pids, so a pid-``0`` test double can never signal the
    caller's own group. (#9648, #9794/#9814, #9911)
    """
    kill_process_group(proc)


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
        harness_env: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        """Create a streaming subprocess on the host."""
        if harness_env:
            env = {**(env or {}), **harness_env}
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

    async def _communicate_bounded(
        self,
        proc: asyncio.subprocess.Process,
        stdin_input: bytes | None,
        timeout: float,
        cancel_check: Callable[[], bool] | None,
        cancel_poll_interval: float,
    ) -> tuple[bytes, bytes]:
        """communicate() with an optional cooperative cancel poll (#9577).

        Without *cancel_check* this is a plain ``wait_for(communicate)``. With
        it, the wait is chunked into *cancel_poll_interval* slices; between
        slices ``cancel_check()`` is consulted, and a True verdict group-kills
        the tree and raises ``SubprocessCancelledError`` — the reap happens
        HERE so run_simple's outer handlers own exactly one path each.
        """
        if cancel_check is None:
            return await asyncio.wait_for(
                proc.communicate(input=stdin_input), timeout=timeout
            )
        comm_task = asyncio.ensure_future(proc.communicate(input=stdin_input))
        deadline = _monotonic() + timeout
        try:
            while True:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    raise TimeoutError
                poll = min(cancel_poll_interval, remaining)
                done, _pending = await asyncio.wait({comm_task}, timeout=poll)
                if comm_task in done:
                    return comm_task.result()
                if cancel_check():
                    _reap_process_group(proc)
                    with contextlib.suppress(ProcessLookupError, OSError):
                        await proc.wait()
                    raise SubprocessCancelledError(
                        "cooperative cancel_check tripped mid-run"
                    )
        finally:
            if not comm_task.done():
                comm_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await comm_task

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
        cancel_check: Callable[[], bool] | None = None,
        cancel_poll_interval: float = 5.0,
    ) -> SimpleResult:
        """Run a command on the host and return its output.

        When *input* is provided, it is written to the process's stdin.

        *cancel_check* (#9577) is polled every *cancel_poll_interval* seconds
        while the process runs; when it returns True the whole process group
        is torn down and ``SubprocessCancelledError`` is raised — letting a
        long local subprocess (e.g. a 45-min ``git bisect``) honour a loop's
        kill-switch mid-run without holding the shared gh/git gate.

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
        # #9911 follow-up: register with the runtime-wide reap registry so
        # a stop/shutdown mid-flight reaps this child too (previously only
        # this method's own timeout could).
        track(proc)
        try:
            try:
                stdout_bytes, stderr_bytes = await self._communicate_bounded(
                    proc, input, timeout, cancel_check, cancel_poll_interval
                )
            finally:
                untrack(proc)
        except SubprocessCancelledError:
            # Cooperative cancel (#9577): the group is already reaped inside
            # _communicate_bounded; surface the distinct error to the caller.
            raise
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

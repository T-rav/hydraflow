"""Regression test for issue #6703.

``stream_claude_process`` uses bare ``assert proc.stdout is not None`` (and
likewise for stderr/stdin) after creating the subprocess.  These assertions:

1. Raise ``AssertionError`` instead of a descriptive ``RuntimeError``.
2. Become silent no-ops under ``python -O`` (``PYTHONOPTIMIZE=1``), causing
   the subsequent attribute access to raise ``AttributeError`` with no
   context about the real failure.

This test mocks the subprocess runner to return a process whose stdout/stderr
are ``None`` and verifies that the function raises ``RuntimeError`` with a
helpful message.  Until the fix is applied, these tests are RED — the code
raises ``AssertionError`` instead of ``RuntimeError``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from runner_utils import stream_claude_process

# ---------------------------------------------------------------------------
# Helpers — fake process with None streams
# ---------------------------------------------------------------------------


def _make_fake_process(
    *, stdout: object = None, stderr: object = None, stdin: object = None
) -> asyncio.subprocess.Process:
    """Return a mock ``asyncio.subprocess.Process`` with controllable streams."""
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.stdout = stdout
    proc.stderr = stderr
    proc.stdin = stdin
    proc.pid = 12345
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()
    proc.terminate = MagicMock()
    return proc


def _make_runner(proc: asyncio.subprocess.Process) -> MagicMock:
    """Return a mock ``SubprocessRunner`` that yields *proc*."""
    runner = MagicMock()
    runner.create_streaming_process = AsyncMock(return_value=proc)
    return runner


def _common_kwargs(runner: MagicMock) -> dict:
    """Keyword arguments shared across all test calls."""
    return {
        "cmd": ["claude", "-p", "--output-format", "stream-json"],
        "prompt": "hello",
        "cwd": Path("/tmp"),
        "active_procs": set(),
        "event_bus": MagicMock(),
        "event_data": {},
        "logger": logging.getLogger("test"),
        "runner": runner,
        "gh_token": "fake-token",
    }


# ---------------------------------------------------------------------------
# Tests — expect RuntimeError, currently raises AssertionError (RED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6703 — fix not yet landed", strict=False)
async def test_stdout_none_raises_runtime_error() -> None:
    """proc.stdout is None → should raise RuntimeError, not AssertionError."""
    proc = _make_fake_process(stdout=None, stderr=MagicMock())
    runner = _make_runner(proc)

    with pytest.raises(RuntimeError, match="(?i)stdout"):
        await stream_claude_process(**_common_kwargs(runner))


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6703 — fix not yet landed", strict=False)
async def test_stderr_none_raises_runtime_error() -> None:
    """proc.stderr is None → should raise RuntimeError, not AssertionError."""
    # stdout must be non-None so the first assert passes and we reach the stderr assert
    proc = _make_fake_process(stdout=MagicMock(), stderr=None)
    runner = _make_runner(proc)

    with pytest.raises(RuntimeError, match="(?i)stderr"):
        await stream_claude_process(**_common_kwargs(runner))


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Regression for issue #6703 — fix not yet landed", strict=False)
async def test_stdin_none_raises_runtime_error_when_not_prompt_arg() -> None:
    """proc.stdin is None (non-prompt-arg mode) → should raise RuntimeError."""
    # cmd without -p: stdin is used to send the prompt, so stdin=None is the failure
    proc = _make_fake_process(stdout=MagicMock(), stderr=MagicMock(), stdin=None)
    runner = _make_runner(proc)

    # Without -p flag, stream_claude_process writes prompt via stdin
    kwargs = _common_kwargs(runner)
    kwargs["cmd"] = ["claude", "--output-format", "stream-json"]

    with pytest.raises(RuntimeError, match="(?i)stdin"):
        await stream_claude_process(**kwargs)

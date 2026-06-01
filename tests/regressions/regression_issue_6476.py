"""Regression test for issue #6476.

Bug: ``stream_claude_process`` does not call ``proc.wait()`` in its
``finally`` block.  When ``proc.stdin.write()`` or ``drain()`` raises
(lines 133-135), the exception propagates before ``stderr_task`` is
created (line 138).  The ``finally`` block:

  1. Skips stderr_task cancellation (``stderr_task is None``).
  2. Discards proc from ``active_procs``.
  3. **Never calls ``proc.kill()`` or ``proc.wait()``** — zombie subprocess.

The subprocess is left running and un-reaped because ``proc.wait()``
is only called inside ``_stream_body()`` (line 208) and in the
``TimeoutError`` handler (line 265).  Any other exception path skips it.

Expected behaviour after fix:
  - ``proc.wait()`` is always called in the ``finally`` block regardless
    of where the exception originated.
  - ``proc.kill()`` is called before ``proc.wait()`` on error paths.
  - ``stderr_task`` is always cancelled in the ``finally`` block when created.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from runner_utils import stream_claude_process

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_kwargs(event_bus, **overrides):
    """Build default kwargs for stream_claude_process.

    Uses ``cmd=["claude"]`` (no ``-p``) so stdin piping is used,
    exercising the stdin write path (lines 131-135).
    """
    defaults = {
        "cmd": ["claude"],
        "prompt": "test prompt",
        "cwd": Path("/tmp/test"),
        "active_procs": set(),
        "event_bus": event_bus,
        "event_data": {"issue": 1},
        "logger": logging.getLogger("test"),
    }
    defaults.update(overrides)
    return defaults


def _make_stdin_failing_proc(*, fail_on: str = "write"):
    """Build a mock process whose stdin.write() or stdin.drain() raises.

    The subprocess is successfully created (stdout/stderr are valid)
    but the stdin write path fails before stderr_task is created.
    """
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 12345

    # stdin — configure the failure point
    mock_proc.stdin = MagicMock()
    if fail_on == "write":
        mock_proc.stdin.write = MagicMock(side_effect=OSError("Broken pipe"))
        mock_proc.stdin.drain = AsyncMock()
    elif fail_on == "drain":
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock(side_effect=OSError("Broken pipe"))
    else:
        msg = f"Unknown fail_on={fail_on!r}"
        raise ValueError(msg)

    mock_proc.stdin.close = MagicMock()

    # stdout/stderr — valid but unused because we fail before reading
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.read = AsyncMock(return_value=b"")

    # kill/wait — these should be called on cleanup but currently aren't
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    return mock_proc


# ---------------------------------------------------------------------------
# Bug 1: stdin write failure leaves zombie subprocess
# ---------------------------------------------------------------------------


class TestStdinWriteFailureZombieSubprocess:
    """When stdin.write() or drain() raises, proc must be killed and reaped.

    Current code: the exception propagates before stderr_task is created.
    The finally block skips everything except active_procs.discard(proc).
    proc.kill() and proc.wait() are never called — zombie subprocess.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6476 — fix not yet landed", strict=False)
    async def test_stdin_write_failure_calls_proc_wait(self, event_bus) -> None:
        """proc.wait() must be called even when stdin.write() raises.

        Current buggy code never calls proc.wait() on this path — RED.
        """
        mock_proc = _make_stdin_failing_proc(fail_on="write")
        mock_create = AsyncMock(return_value=mock_proc)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(OSError, match="Broken pipe"),
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        (
            mock_proc.wait.assert_awaited(),
            (
                "Bug #6476: proc.wait() was never called after stdin.write() "
                "failure — subprocess left as zombie"
            ),
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6476 — fix not yet landed", strict=False)
    async def test_stdin_drain_failure_calls_proc_wait(self, event_bus) -> None:
        """proc.wait() must be called even when stdin.drain() raises.

        Current buggy code never calls proc.wait() on this path — RED.
        """
        mock_proc = _make_stdin_failing_proc(fail_on="drain")
        mock_create = AsyncMock(return_value=mock_proc)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(OSError, match="Broken pipe"),
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        (
            mock_proc.wait.assert_awaited(),
            (
                "Bug #6476: proc.wait() was never called after stdin.drain() "
                "failure — subprocess left as zombie"
            ),
        )

    @pytest.mark.asyncio
    async def test_stdin_write_failure_removes_from_active_procs(
        self, event_bus
    ) -> None:
        """Process must be removed from active_procs on stdin failure.

        This path IS handled correctly by current code (the finally block
        calls active_procs.discard). Included as a GREEN guard to ensure
        the fix doesn't regress this.
        """
        mock_proc = _make_stdin_failing_proc(fail_on="write")
        mock_create = AsyncMock(return_value=mock_proc)
        active_procs: set = set()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(OSError),
        ):
            await stream_claude_process(
                **_default_kwargs(event_bus, active_procs=active_procs)
            )

        assert mock_proc not in active_procs, (
            "proc should be removed from active_procs on stdin failure"
        )


# ---------------------------------------------------------------------------
# Bug 2: proc.wait() missing from finally block on general exception paths
# ---------------------------------------------------------------------------


class TestProcWaitAlwaysCalledInFinally:
    """proc.wait() must be called in the finally block for ALL exception paths.

    Currently proc.wait() is only called:
      - Inside _stream_body() (line 208) — normal path
      - In the TimeoutError handler (line 265)

    Any other exception that escapes the try block (stdin failure,
    unexpected error during stream setup) skips proc.wait().
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6476 — fix not yet landed", strict=False)
    async def test_unexpected_error_after_stderr_task_calls_proc_wait(
        self, event_bus
    ) -> None:
        """When an unexpected error occurs after stderr_task is created but
        outside _stream_body, proc.wait() must still be called.

        We simulate this by making StreamParser() raise during construction.
        stderr_task is created at line 138, StreamParser() at line 140.
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        mock_create = AsyncMock(return_value=mock_proc)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            patch(
                "runner_utils.StreamParser",
                side_effect=RuntimeError("parser init failed"),
            ),
            pytest.raises(RuntimeError, match="parser init failed"),
        ):
            await stream_claude_process(**_default_kwargs(event_bus))

        # The finally block correctly cancels stderr_task (it was created
        # before StreamParser raised), but proc.wait() is still not called.
        (
            mock_proc.wait.assert_awaited(),
            (
                "Bug #6476: proc.wait() was never called after StreamParser "
                "init failure — subprocess left as zombie"
            ),
        )

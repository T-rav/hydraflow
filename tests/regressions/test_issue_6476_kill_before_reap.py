"""The unconditional reap must be preceded by a kill on error paths.

#6476 added `await proc.wait()` to `stream_claude_process`'s `finally` so a
subprocess is never left unreaped. On its own that is a hazard rather than a
fix: if the child is still alive — a wedged agent that closed our stdin but
did not exit — an unconditional wait blocks forever, converting a leaked
process into a hung loop.

The `except BaseException: _kill_proc_group(proc)` clause ahead of the
`finally` is what makes the reap safe, and #6476's own tests do not cover it:
their fake `wait` returns immediately, so deleting the kill leaves every one
of them green. This pins the ordering.

`kill_process_group` is patched rather than exercised: the fake process
carries a MagicMock pid, and letting that reach `os.killpg` is the mock-pid
hazard `process_group` documents.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runner_utils import StreamConfig, stream_claude_process


def _wedged_proc() -> MagicMock:
    """A process whose stdin write fails and which never exits on its own."""
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.pid = 12345
    proc.returncode = None
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock(side_effect=OSError("Broken pipe"))
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


@pytest.mark.asyncio
async def test_error_path_kills_the_group_before_reaping() -> None:
    """The kill is ordered ahead of the wait, not merely also present."""
    proc = _wedged_proc()
    runner = MagicMock()
    runner.create_streaming_process = AsyncMock(return_value=proc)

    order: list[str] = []
    proc.wait = AsyncMock(side_effect=lambda: order.append("wait"))

    with (
        patch(
            "runner_utils.kill_process_group",
            side_effect=lambda _p: order.append("kill"),
        ) as killer,
        pytest.raises(OSError, match="Broken pipe"),
    ):
        await stream_claude_process(
            # No `-p`: that routes the prompt as an argument and leaves
            # stdin on DEVNULL, skipping the write path entirely.
            cmd=["claude"],
            prompt="hello",
            cwd=Path("/tmp"),
            active_procs=set(),
            event_bus=MagicMock(),
            event_data={},
            logger=logging.getLogger("test"),
            config=StreamConfig(runner=runner),
        )

    killer.assert_called_once_with(proc)
    assert order == ["kill", "wait"], (
        "The group kill must precede the reap — a wait on a still-running "
        f"child never returns. Observed order: {order}"
    )

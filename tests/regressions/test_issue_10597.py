"""Regression: the implement agent must fail fast on a MID-RUN credit
exhaustion instead of hanging the full 3600s hard timeout (#10597).

Incident — 2026-07-26 (live factory). An implement agent hit the Anthropic
*weekly* subscription cap partway through a run. The Claude CLI did not exit:
it sat in api-retry/backoff, emitting the limit line into stdout but never
closing the stream. ``runner_utils._stream_and_collect`` only checked for
credit exhaustion *after* the stream ended (in ``_post_stream_result``), so
the ``async for raw in proc.stdout`` read loop blocked until the 3600s hard
cap fired — burning ~1h per attempt, seen 3x in one run.

Worse than the wasted hour: a hard-timeout surfaces as a generic
``RuntimeError("Agent process timed out")``, which the orchestrator counts as
an ordinary failed attempt and burns the retry budget. Detecting the credit
signal in-stream and raising ``CreditExhaustedError`` instead routes it through
``reraise_on_credit_or_bug`` to the global pause/park (and an attempt refund),
so the budget is preserved.

These tests pin the fix WITHOUT a real 3600s wait: the fake stdout emits a
credit line mid-stream and would then hang "forever" (a stand-in for the stuck
CLI). With the fix the run raises ``CreditExhaustedError`` in milliseconds and
never reaches the hang; the whole call is guarded by a small ``wait_for`` so a
regression fails loudly (as an ``asyncio.TimeoutError``) instead of hanging the
suite.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from runner_utils import StreamConfig, stream_claude_process
from subprocess_util import CreditExhaustedError

# The real hard cap. A pre-fix run blocks on stdout until this fires; the fix
# must break out long before, so we never actually wait it out.
HARD_TIMEOUT = 3600.0
# Bound on how long the *test* is willing to run. Comfortably above the
# millisecond fast-fail but far below the hard cap, so a regression that falls
# through to the hang trips this instead of hanging pytest.
TEST_GUARD_TIMEOUT = 5.0

# Realistic Claude-Code stream-json weekly-cap frame (the 2026-06-17 wording).
# The limit line arrives mid-stream while the CLI keeps retrying.
WEEKLY_LIMIT_TEXT = "You've hit your weekly limit · resets Jun 18 at 5pm"


def _assistant_frame(text: str, msg_id: str) -> str:
    """A minimal Claude stream-json ``assistant`` frame carrying *text*.

    Each real assistant message has its own ``id``; distinct ids matter because
    ``StreamParser`` emits only the *delta* since the previous same-id frame, so
    a shared id would truncate the second frame's leading text.
    """
    import json

    return json.dumps(
        {
            "type": "assistant",
            "message": {"id": msg_id, "content": [{"type": "text", "text": text}]},
        }
    )


class _CreditThenHangStdout:
    """Async stdout iterator that emits normal lines, then a credit line, then
    hangs ~forever — modelling the CLI stuck in api-retry after the cap.

    ``hang_reached`` records whether the read loop advanced *past* the credit
    line into the hang; the fix must break out before that, so it stays False.
    """

    def __init__(self, pre_lines: list[str], credit_line: str) -> None:
        queued = [*pre_lines, credit_line]
        self._lines = [(ln + "\n").encode() for ln in queued]
        self._idx = 0
        self.hang_reached = False

    def __aiter__(self) -> _CreditThenHangStdout:
        return self

    async def __anext__(self) -> bytes:
        if self._idx < len(self._lines):
            line = self._lines[self._idx]
            self._idx += 1
            return line
        # Past the credit line: the real CLI never closes stdout here.
        self.hang_reached = True
        await asyncio.sleep(HARD_TIMEOUT)
        raise StopAsyncIteration


def _make_hanging_credit_proc(stdout: _CreditThenHangStdout) -> AsyncMock:
    """Build a mock subprocess whose stdout is *stdout*.

    ``pid`` is None so any reap goes through ``kill_process_group``'s
    child-only ``proc.kill()`` fallback (never a real ``os.killpg``), matching
    ``tests.helpers.make_streaming_proc``.
    """
    proc = MagicMock()
    proc.returncode = None
    proc.pid = None
    proc.stdin = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = stdout
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    return proc


def _kwargs(event_bus: object, active_procs: set) -> dict:
    return {
        "cmd": ["claude", "-p"],
        "prompt": "implement issue",
        "cwd": Path("/tmp/test-10597"),
        "active_procs": active_procs,
        "event_bus": event_bus,
        "event_data": {"issue": 10597, "source": "implementer"},
        "logger": logging.getLogger("test-10597"),
    }


@pytest.mark.asyncio
async def test_mid_run_credit_line_fails_fast_not_after_hard_timeout(
    event_bus,
) -> None:
    """A credit line emitted mid-stream raises CreditExhaustedError promptly —
    long before the 3600s hard cap and without reaching the stuck-CLI hang."""
    stdout = _CreditThenHangStdout(
        pre_lines=[_assistant_frame("Working on the fix...", msg_id="m1")],
        credit_line=_assistant_frame(WEEKLY_LIMIT_TEXT, msg_id="m2"),
    )
    proc = _make_hanging_credit_proc(stdout)
    active_procs: set = set()
    loop = asyncio.get_running_loop()

    start = loop.time()
    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("process_group.os.killpg"),
        pytest.raises(CreditExhaustedError),
    ):
        # The guard wraps the call so a regression (which would block on the
        # hang until HARD_TIMEOUT) fails as a TimeoutError here rather than
        # hanging the suite — it never lets the real 3600s elapse.
        await asyncio.wait_for(
            stream_claude_process(
                **_kwargs(event_bus, active_procs),
                config=StreamConfig(timeout=HARD_TIMEOUT),
            ),
            timeout=TEST_GUARD_TIMEOUT,
        )
    elapsed = loop.time() - start

    # Fast: resolved in a blink, nowhere near the hard cap.
    assert elapsed < 2.0, f"expected a fast fail, took {elapsed:.2f}s"
    # Broke out BEFORE waiting on the stuck stream.
    assert stdout.hang_reached is False
    # The stuck process was reaped (child-only kill for the mock pid).
    proc.kill.assert_called()
    # Fail-fast must not leak the process into the active set.
    assert active_procs == set()


@pytest.mark.asyncio
async def test_fast_fail_raises_credit_error_not_generic_timeout(event_bus) -> None:
    """The mid-run bail raises CreditExhaustedError (→ pause/refund, budget
    preserved), NOT the generic hard-timeout RuntimeError (→ counted attempt)."""
    stdout = _CreditThenHangStdout(
        pre_lines=[],
        credit_line="Claude usage limit reached. resets 3am (America/Denver)",
    )
    proc = _make_hanging_credit_proc(stdout)

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("process_group.os.killpg"),
        pytest.raises(CreditExhaustedError) as exc_info,
    ):
        await asyncio.wait_for(
            stream_claude_process(
                **_kwargs(event_bus, set()),
                config=StreamConfig(timeout=HARD_TIMEOUT),
            ),
            timeout=TEST_GUARD_TIMEOUT,
        )

    # A parseable resume time keeps the pause the right length instead of
    # falling back to the default 5h wake-up.
    assert exc_info.value.resume_at is not None
    assert not isinstance(exc_info.value, TimeoutError)


@pytest.mark.asyncio
async def test_fast_fail_when_cap_phrase_split_across_deltas(event_bus) -> None:
    """The cap phrase caught even when it arrives split across same-message
    stream deltas (StreamParser emits only the per-delta suffix).

    Two frames share a message id, so the parser yields ``"You've hit your"``
    then ``" weekly limit · resets ..."`` — no single display line carries the
    whole phrase. The bounded accumulated-text tail scan still detects it; a
    per-line-only scan would miss it and fall through to the hang.
    """
    stdout = _CreditThenHangStdout(
        pre_lines=[_assistant_frame("You've hit your", msg_id="cap")],
        credit_line=_assistant_frame(
            "You've hit your weekly limit · resets Jun 18 at 5pm", msg_id="cap"
        ),
    )
    proc = _make_hanging_credit_proc(stdout)

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("process_group.os.killpg"),
        pytest.raises(CreditExhaustedError),
    ):
        await asyncio.wait_for(
            stream_claude_process(
                **_kwargs(event_bus, set()),
                config=StreamConfig(timeout=HARD_TIMEOUT),
            ),
            timeout=TEST_GUARD_TIMEOUT,
        )

    assert stdout.hang_reached is False


@pytest.mark.asyncio
async def test_credit_prose_scan_disabled_does_not_fast_fail(event_bus) -> None:
    """Runners that quote credit-error prose (DiagnosticRunner sets
    credit_prose_scan=False) must NOT self-trip on a mid-stream credit line.

    The stream ends normally (no hang) and the call returns the transcript
    without raising — proving the mid-run scan honours the same gate as the
    post-stream check.
    """
    import json

    lines = "\n".join(
        [
            _assistant_frame("Quoting the failure transcript:", msg_id="d1"),
            _assistant_frame(WEEKLY_LIMIT_TEXT, msg_id="d2"),
            json.dumps({"type": "result", "result": "diagnosis complete"}),
        ]
    )
    # A normal (non-hanging) stream: quality proc that closes stdout cleanly.
    from tests.helpers import make_streaming_proc

    mock_create = make_streaming_proc(returncode=0, stdout=lines)
    proc = await mock_create()
    proc.returncode = 0

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("process_group.os.killpg"),
    ):
        transcript = await asyncio.wait_for(
            stream_claude_process(
                **_kwargs(event_bus, set()),
                config=StreamConfig(timeout=HARD_TIMEOUT, credit_prose_scan=False),
            ),
            timeout=TEST_GUARD_TIMEOUT,
        )

    assert "diagnosis complete" in transcript

"""Regression test for issue #6475.

shape_phase.ShapePhase._check_for_response() wraps the WhatsApp state
read (``self._state.get_shape_response(issue.id)``) in a bare
``except Exception: pass`` block with no logging.  When the state store
throws (corrupt state, missing key, lock contention), the WhatsApp reply
is silently discarded — no log line, no diagnostic trail.  The issue
then falls through to the slower GitHub comment path and the human
thinks their WhatsApp response was ignored.

Test 1 (AST): proves the silent ``except Exception: pass`` still exists
in ``_check_for_response``.

Test 2 (behavioral): calls ``_check_for_response`` with a state that
raises on ``get_shape_response`` and asserts that a log message is
emitted.  Currently FAILS because the bare ``pass`` produces no output.
"""

from __future__ import annotations

import ast
import inspect
import logging
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shape_phase import ShapePhase

# ---------------------------------------------------------------------------
# Test 1: AST — prove the silent except block exists
# ---------------------------------------------------------------------------


class TestSilentExceptBlockExists:
    """The except handler in _check_for_response must not silently ``pass``."""

    @pytest.mark.xfail(reason="Regression for issue #6475 — fix not yet landed", strict=False)
    def test_check_for_response_has_no_silent_except(self) -> None:
        """Parse _check_for_response and assert there is no
        ``except Exception: pass`` (i.e. a handler whose only statement
        is ``pass`` with no logging call).
        """
        source = textwrap.dedent(inspect.getsource(ShapePhase._check_for_response))
        tree = ast.parse(source)

        silent_blocks: list[int] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ExceptHandler)
                and node.type is not None
                and isinstance(node.type, ast.Name)
                and node.type.id == "Exception"
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                silent_blocks.append(node.lineno)

        assert not silent_blocks, (
            f"ShapePhase._check_for_response contains a silent "
            f"`except Exception: pass` at relative source line(s) "
            f"{silent_blocks}. It should log at debug level with exc_info=True "
            f"so that swallowed WhatsApp state-read failures are observable."
        )


# ---------------------------------------------------------------------------
# Test 2: Behavioral — exception on state read must produce a log message
# ---------------------------------------------------------------------------


def _make_shape_phase() -> tuple[ShapePhase, MagicMock]:
    """Build a ShapePhase with just enough mocks for _check_for_response."""
    config = MagicMock()
    state = MagicMock()
    store = MagicMock()
    store.enrich_with_comments = AsyncMock(
        return_value=MagicMock(comments=[]),
    )
    prs = MagicMock()
    event_bus = MagicMock()
    stop_event = MagicMock()

    phase = ShapePhase(
        config=config,
        state=state,
        store=store,
        prs=prs,
        event_bus=event_bus,
        stop_event=stop_event,
    )
    return phase, state


class TestWhatsAppStateErrorLogsMessage:
    """When get_shape_response raises, _check_for_response must log it."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6475 — fix not yet landed", strict=False)
    async def test_state_read_exception_emits_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Simulate a corrupt-state RuntimeError from get_shape_response.

        After the fix the except block should emit at least a debug-level
        log.  Currently FAILS because the bare ``pass`` produces nothing.
        """
        phase, state = _make_shape_phase()
        issue = MagicMock()
        issue.id = 42

        # State read blows up — simulates corrupt JSON, lock contention, etc.
        state.get_shape_response.side_effect = RuntimeError(
            "Corrupt state: unexpected EOF in shape_responses"
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.shape_phase"):
            result = await phase._check_for_response(issue)

        # The method should still return (it falls through to GitHub path),
        # but crucially it must LOG the failure — not silently swallow it.
        # result is None because the GitHub mock also returns no comments.
        assert result is None, "Expected None (no response from either source)"

        relevant_logs = [
            r
            for r in caplog.records
            if r.levelno >= logging.DEBUG
            and (
                "whatsapp" in r.message.lower()
                or "state" in r.message.lower()
                or "shape_response" in r.message.lower()
                or "corrupt" in r.message.lower()
            )
        ]
        assert relevant_logs, (
            "Expected at least one log record when get_shape_response raises "
            "RuntimeError, but the exception was silently swallowed with no "
            "diagnostic output. The bare `except Exception: pass` at "
            "shape_phase.py:473-474 discards the error."
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6475 — fix not yet landed", strict=False)
    async def test_state_read_exception_preserves_exc_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The log record should include exc_info so the traceback is available."""
        phase, state = _make_shape_phase()
        issue = MagicMock()
        issue.id = 99

        state.get_shape_response.side_effect = KeyError("missing_key")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.shape_phase"):
            await phase._check_for_response(issue)

        records_with_exc = [
            r for r in caplog.records if r.exc_info and r.exc_info[0] is not None
        ]
        assert records_with_exc, (
            "Expected the log record for the swallowed exception to include "
            "exc_info=True so the traceback is preserved for debugging. "
            "Currently no log is emitted at all (bare `except Exception: pass`)."
        )

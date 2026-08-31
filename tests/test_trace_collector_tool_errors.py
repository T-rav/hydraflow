"""Tool-error capture in TraceCollector (§0 of the retro-evidence spec).

`TraceToolProfile.tool_errors` and `ToolCallSpan.error` were declared on the
model but never populated by the collector: `_handle_user_tool_result` flipped
every span to ``succeeded=True`` without reading ``is_error``, and
``tool_errors`` only ever received the literal key ``"__stream__"``. Every
existing test built ``TraceToolProfile`` by hand, so the fields were pinned at
the model level and never at the collector level.

These tests drive the real collector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import ConfigFactory
from trace_collector import TraceCollector  # noqa: E402


def _make_collector(tmp_path: Path) -> TraceCollector:
    config = ConfigFactory.create()
    config.data_root = tmp_path
    return TraceCollector(
        issue_number=42,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )


def _tool_use(tool_id: str, name: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": name,
                        "input": {"command": "make quality"},
                    }
                ]
            },
        }
    )


def _tool_result(tool_id: str, *, is_error: bool, content: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "is_error": is_error,
                        "content": content,
                    }
                ]
            },
        }
    )


class TestClaudeToolErrorCapture:
    def test_failed_tool_result_marks_span_not_succeeded(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(_tool_result("t1", is_error=True, content="make: *** Error 1"))

        assert c.tool_calls[0].succeeded is False

    def test_failed_tool_result_records_error_text_on_span(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(_tool_result("t1", is_error=True, content="make: *** Error 1"))

        assert c.tool_calls[0].error == "make: *** Error 1"

    def test_failed_tool_result_counts_against_the_tool_name(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(_tool_result("t1", is_error=True, content="make: *** Error 1"))

        assert c.tool_errors == {"Bash": 1}

    def test_successful_tool_result_records_no_error(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(_tool_result("t1", is_error=False, content="ok"))

        span = c.tool_calls[0]
        assert (span.succeeded, span.error, c.tool_errors) == (True, None, {})

    def test_error_counts_accumulate_per_tool(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        for idx, name in enumerate(["Bash", "Bash", "Edit"]):
            tool_id = f"t{idx}"
            c.record(_tool_use(tool_id, name))
            c.record(_tool_result(tool_id, is_error=True, content="boom"))

        assert c.tool_errors == {"Bash": 2, "Edit": 1}

    def test_finalized_trace_carries_the_error_profile(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(_tool_result("t1", is_error=True, content="make: *** Error 1"))

        trace = c.finalize(success=False)

        assert trace is not None
        assert trace.tools.tool_errors == {"Bash": 1}


class TestStreamErrorText:
    def test_stream_error_message_is_kept_not_dropped(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(json.dumps({"type": "error", "message": "connection reset"}))

        assert "connection reset" in c.stream_errors


class TestUnverifiedBackendsAreExplicitGaps:
    """Pi and Codex error shapes are not authoritative anywhere in-repo.

    `_parse_pi_tool_end` reads only ``result``; `_parse_codex_item` reads only
    ``type``/``text``; `tests/fixtures/stream_json/` holds a Claude sample and
    nothing else. Guessing a field name would ship a sentinel that silently
    never matches. These pin the gap so the follow-up has a target to flip.
    """

    def test_pi_tool_end_does_not_yet_record_errors(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "tool_execution_start",
                    "toolName": "Bash",
                    "args": {},
                    "invocationId": "p1",
                }
            )
        )
        c.record(
            json.dumps(
                {
                    "type": "tool_execution_end",
                    "toolName": "Bash",
                    "invocationId": "p1",
                    "result": "boom",
                }
            )
        )

        assert c.tool_errors == {}, "pi error capture landed — flip this test"

    def test_codex_function_call_has_no_completion_handler(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "function_call",
                        "name": "shell",
                        "arguments": "{}",
                        "id": "c1",
                    },
                }
            )
        )

        assert c.tool_calls[0].succeeded is False, "codex completion landed"
        assert c.tool_errors == {}, "codex error capture landed — flip this test"


class TestStreamErrorsReachTheTrace:
    """In-memory capture is not enough — the retro reads finalized traces."""

    def test_finalize_carries_stream_error_into_trace_error(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(_tool_use("t1", "Bash"))
        c.record(json.dumps({"type": "error", "message": "connection reset"}))

        trace = c.finalize(success=False)

        assert trace is not None
        assert trace.error is not None
        assert "connection reset" in trace.error

    def test_stream_error_alone_still_produces_a_trace(self, tmp_path: Path):
        """A subprocess that only ever errored is the case retro cares most about."""
        c = _make_collector(tmp_path)
        c.record(json.dumps({"type": "error", "message": "auth failed"}))

        trace = c.finalize(success=False)

        assert trace is not None, "stream-error-only subprocess wrote no trace"
        assert "auth failed" in (trace.error or "")


class TestStreamErrorsAreBounded:
    def test_stream_errors_do_not_grow_without_limit(self, tmp_path: Path):
        """A failing subprocess can emit error events indefinitely."""
        c = _make_collector(tmp_path)
        for i in range(200):
            c.record(json.dumps({"type": "error", "message": f"err {i}"}))

        assert len(c.stream_errors) <= 20
        assert "err 199" in c.stream_errors[-1], "newest error must be kept"

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


class TestPiAndCodexNowRecordToolErrors:
    """Flipped from `TestUnverifiedBackendsAreExplicitGaps` (#11889).

    These pinned the GAP — Pi captured no errors and Codex had no completion
    handler at all — so the follow-up had a target. Both landed, and the
    conditions the old tests carried ("flip this test") are met.

    They now pin the two properties that replaced the gap, and the second one
    is as important as the first: capture reads an ENUMERATED set of failure
    markers, so an event with no marker is UNKNOWN and must not be promoted to
    "failed". A capture that called every completion a failure would satisfy
    "errors are recorded" while being useless.
    """

    def test_a_marked_pi_failure_is_captured(self, tmp_path: Path):
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
                    "isError": True,
                    "result": "boom",
                }
            )
        )

        assert c.tool_errors == {"Bash": 1}
        assert c.tool_calls[0].succeeded is False
        assert c.tool_calls[0].error is not None

    def test_an_unmarked_pi_result_is_not_assumed_to_have_failed(self, tmp_path: Path):
        """`result: "boom"` is output text, not a failure marker.

        Promoting unmarked completions to failures would make `tool_errors`
        count every Pi tool call, which is the mirror-image defect of the one
        this fixed: a signal that is always on carries no information.
        """
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

        assert c.tool_errors == {}
        assert c.tool_calls[0].succeeded is True

    def test_a_codex_completion_closes_the_span(self, tmp_path: Path):
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
        c.record(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "function_call_output",
                        "call_id": "c1",
                        "output": "boom",
                        "is_error": True,
                    },
                }
            )
        )

        assert c.tool_errors == {"shell": 1}
        assert c.tool_calls[0].error is not None

    def test_an_unterminated_codex_call_stays_open(self, tmp_path: Path):
        """A `function_call` with no completion is "never closed", not "failed".

        Preserved from the gap tests deliberately: `retro_signals` keys on
        `error is not None` precisely because an open span reports
        `succeeded=False`, and that must keep meaning "no verdict yet".
        """
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

        assert c.tool_calls[0].succeeded is False
        assert c.tool_calls[0].error is None
        assert c.tool_errors == {}


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

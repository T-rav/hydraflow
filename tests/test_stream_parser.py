"""Tests for dx/hydraflow/stream_parser.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from stream_parser import StreamParser, _summarize_input

# ===========================================================================
# _summarize_input — direct unit tests
# ===========================================================================


def test_summarize_input_bash_truncation():
    """Bash command longer than 120 chars is truncated to 120."""
    long_cmd = "x" * 200
    result = _summarize_input("Bash", {"command": long_cmd})
    assert len(result) == 120
    assert result == long_cmd[:120]


def test_summarize_input_generic_fallback_truncation():
    """Generic fallback with input > 120 chars adds '...' suffix."""
    long_val = "a" * 200
    result = _summarize_input("UnknownTool", {"data": long_val})
    assert result.endswith("...")
    assert len(result) == 123  # 120 + "..."


def test_summarize_input_generic_fallback_no_truncation():
    """Generic fallback with short input does not add '...' suffix."""
    result = _summarize_input("UnknownTool", {"x": 1})
    assert not result.endswith("...")


def test_summarize_input_task_truncation():
    """Task description longer than 120 chars is truncated."""
    long_desc = "d" * 200
    result = _summarize_input("Task", {"description": long_desc})
    assert len(result) == 120


def test_summarize_input_task_with_agent_truncation():
    """Task with agent and long description is truncated to 120 total."""
    long_desc = "d" * 200
    result = _summarize_input(
        "Task", {"description": long_desc, "subagent_type": "Explore"}
    )
    assert len(result) == 120
    assert result.startswith("Explore: ")


def test_summarize_input_edit_shows_only_file_path():
    """Edit summary shows only file_path, not old/new text."""
    result = _summarize_input(
        "Edit",
        {
            "file_path": "/src/foo.py",
            "old_text": "old stuff",
            "new_text": "new stuff",
        },
    )
    assert result == "/src/foo.py"


def test_summarize_input_write_shows_only_file_path():
    """Write summary shows only file_path, not content."""
    result = _summarize_input(
        "Write",
        {
            "file_path": "/src/bar.py",
            "content": "lots of code",
        },
    )
    assert result == "/src/bar.py"


def test_summarize_input_glob_shows_pattern():
    """Glob summary shows the pattern."""
    result = _summarize_input("Glob", {"pattern": "**/*.ts"})
    assert result == "**/*.ts"


# ===========================================================================
# StreamParser (stateful) — delta tracking
# ===========================================================================


class TestStreamParserDelta:
    """StreamParser deduplicates cumulative assistant message events."""

    def test_first_message_returns_text(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == "Hello"

    def test_cumulative_message_returns_only_delta(self):
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello world"}],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert display == "world"

    def test_same_text_returns_empty(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        parser.parse(json.dumps(event))
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_new_turn_resets_text_tracking(self):
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Turn 1 text"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_2",
                "content": [{"type": "text", "text": "Turn 2 text"}],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert display == "Turn 2 text"

    def test_tool_use_shown_once(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "/a.py"},
                    },
                ],
            },
        }
        d1, _ = parser.parse(json.dumps(event))
        d2, _ = parser.parse(json.dumps(event))
        assert "Read" in d1
        assert d2 == ""  # already seen this tool_id

    def test_cumulative_message_with_new_tool(self):
        """Second snapshot adds a tool_use — only the tool is new."""
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Let me look"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {"type": "text", "text": "Let me look"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Glob",
                        "input": {"pattern": "**/*.py"},
                    },
                ],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert "Glob" in display
        assert "Let me look" not in display  # text unchanged

    def test_result_event_still_captured(self):
        parser = StreamParser()
        event = {"type": "result", "result": "Final output"}
        display, result = parser.parse(json.dumps(event))
        assert display == ""
        assert result == "Final output"

    def test_plain_text_passes_through(self):
        parser = StreamParser()
        display, result = parser.parse("not json")
        assert display == "not json"
        assert result is None

    def test_user_tool_result_shown(self):
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "File contents here...",
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "File contents here" in display

    def test_user_message_multiple_tool_results(self):
        """Only the first tool_result's preview appears (early return)."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "First result",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "content": "Second result",
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "First result" in display
        assert "Second result" not in display

    def test_codex_item_completed_agent_message(self):
        parser = StreamParser()
        event = {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": "hello"},
        }
        display, result = parser.parse(json.dumps(event))
        assert display == "hello"
        assert result is None

    def test_codex_turn_completed_uses_last_agent_message(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "agent_message", "text": "done"},
                }
            )
        )
        display, result = parser.parse(json.dumps({"type": "turn.completed"}))
        assert display == ""
        assert result == "done"

    def test_user_message_non_tool_result_content(self):
        """User event with only text content (no tool_result) returns empty."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Some user text"},
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_user_message_empty_content(self):
        """User event with empty content list returns empty."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {"content": []},
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_user_tool_result_long_content_truncated(self):
        """User tool_result content > 80 chars is truncated with ellipsis."""
        parser = StreamParser()
        long_content = "x" * 100
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": long_content,
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "…" in display
        # The preview part (after "    ← ") should be 80 chars + ellipsis
        preview = display.replace("    ← ", "")
        assert len(preview) == 81  # 80 chars + "…"

    def test_captures_usage_from_result_event(self):
        parser = StreamParser()
        event = {
            "type": "result",
            "result": "done",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 45,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 10,
                "total_tokens": 165,
            },
        }
        parser.parse(json.dumps(event))
        usage = parser.usage_totals
        assert usage["input_tokens"] == 120
        assert usage["output_tokens"] == 45
        assert usage["cache_creation_input_tokens"] == 30
        assert usage["cache_read_input_tokens"] == 10
        assert usage["total_tokens"] == 165

    def test_usage_tracks_max_for_cumulative_events(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "assistant",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "message": {"id": "m1", "content": [{"type": "text", "text": "a"}]},
                }
            )
        )
        parser.parse(
            json.dumps(
                {
                    "type": "assistant",
                    "usage": {"input_tokens": 90, "output_tokens": 15},
                    "message": {
                        "id": "m1",
                        "content": [{"type": "text", "text": "ab"}],
                    },
                }
            )
        )
        usage = parser.usage_totals
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 20

    def test_usage_ignores_token_like_keys_in_tool_payloads(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "m2",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"input_tokens": 9999, "total_tokens": 9999},
                    }
                ],
            },
        }
        parser.parse(json.dumps(event))
        usage = parser.usage_totals
        assert usage["input_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_pi_message_update_text_delta(self):
        parser = StreamParser()
        event = {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "Hello from pi"},
        }
        display, result = parser.parse(json.dumps(event))
        assert display == "Hello from pi"
        assert result is None

    def test_pi_message_update_preserves_whitespace_in_result(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"},
                }
            )
        )
        parser.parse(
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": " world"},
                }
            )
        )
        _display, result = parser.parse(json.dumps({"type": "agent_end"}))
        assert result == "Hello world"

    def test_pi_tool_execution_start_and_end(self):
        parser = StreamParser()
        start = {
            "type": "tool_execution_start",
            "toolName": "read",
            "args": {"file_path": "src/main.py"},
        }
        end = {
            "type": "tool_execution_end",
            "toolName": "read",
            "result": "file contents",
            "isError": False,
        }
        start_display, _ = parser.parse(json.dumps(start))
        end_display, _ = parser.parse(json.dumps(end))
        assert "read" in start_display
        assert "file contents" in end_display

    def test_pi_agent_end_returns_last_result_text(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "Final"},
                }
            )
        )
        display, result = parser.parse(
            json.dumps({"type": "agent_end", "messages": []})
        )
        assert display == ""
        assert result == "Final"

    def test_pi_usage_keys_are_mapped_to_canonical_totals(self):
        parser = StreamParser()
        event = {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "HI"}],
                "usage": {
                    "input": 100,
                    "output": 7,
                    "cacheRead": 5,
                    "cacheWrite": 3,
                    "totalTokens": 115,
                },
            },
        }
        parser.parse(json.dumps(event))
        usage = parser.usage_totals
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 7
        assert usage["cache_read_input_tokens"] == 5
        assert usage["cache_creation_input_tokens"] == 3
        assert usage["total_tokens"] == 115

    def test_usage_snapshot_marks_unavailable_when_no_usage_emitted(self):
        parser = StreamParser()
        parser.parse(json.dumps({"type": "assistant", "message": {"content": []}}))
        snap = parser.usage_snapshot
        assert snap["usage_status"] == "unavailable"
        assert snap["usage_available"] is False

    def test_usage_snapshot_tracks_backend_for_codex_events(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "i1",
                        "usage": {"input_tokens": 3, "total_tokens": 5},
                    },
                }
            )
        )
        snap = parser.usage_snapshot
        assert snap["usage_backend"] == "codex"
        assert snap["input_tokens"] == 3


# ===========================================================================
# parse_result_envelope — the one-shot ``claude -p --output-format json`` shape
# ===========================================================================


def _cli_json_envelope(result_text: str, **overrides):
    """A faithful ``claude -p --output-format json`` envelope (CLI 2.1.238)."""
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 1339,
        "duration_api_ms": 1200,
        "num_turns": 1,
        "result": result_text,
        "session_id": "fe99e068-2bfb-4292-b7c2-d5b48beed108",
        "total_cost_usd": 0.0178634,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 7431,
            "cache_read_input_tokens": 18134,
            "output_tokens": 45,
            "output_tokens_details": {"thinking_tokens": 37},
            "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
            "service_tier": "standard",
            "cache_creation": {
                "ephemeral_1h_input_tokens": 7431,
                "ephemeral_5m_input_tokens": 0,
            },
            "iterations": [
                {
                    "input_tokens": 10,
                    "output_tokens": 45,
                    "cache_read_input_tokens": 18134,
                    "cache_creation_input_tokens": 7431,
                    "type": "message",
                }
            ],
        },
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 908,
                "outputTokens": 56,
                "cacheReadInputTokens": 18134,
                "cacheCreationInputTokens": 7431,
                "costUSD": 0.0178634,
            }
        },
        "uuid": "0b4f0d3c-2b0a-4a7e-9a3e-5f6d7c8b9a01",
    }
    envelope.update(overrides)
    return envelope


class TestParseResultEnvelope:
    def test_unwraps_result_text_and_canonical_usage(self):
        from stream_parser import parse_result_envelope

        envelope = parse_result_envelope(json.dumps(_cli_json_envelope("pong")))

        assert envelope is not None
        assert envelope.result == "pong"
        assert envelope.is_error is False
        assert envelope.session_id == "fe99e068-2bfb-4292-b7c2-d5b48beed108"
        usage = envelope.usage
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 45
        assert usage["cache_creation_input_tokens"] == 7431
        assert usage["cache_read_input_tokens"] == 18134
        assert usage["usage_available"] is True
        assert usage["usage_status"] == "available"
        assert usage["usage_backend"] == "claude"

    def test_raw_usage_matches_streaming_shape(self):
        # The cost surfaces already read ``raw_usage`` rows shaped by the
        # streaming extractor; the one-shot envelope must produce the same shape.
        from stream_parser import parse_result_envelope

        envelope = parse_result_envelope(json.dumps(_cli_json_envelope("pong")))

        assert envelope is not None
        raw = envelope.usage["raw_usage"]
        assert isinstance(raw, list) and raw
        assert raw[0]["backend"] == "claude"
        assert raw[0]["event_type"] == "result"
        assert raw[0]["path"] == "usage"
        assert raw[0]["payload"]["output_tokens"] == 45

    def test_nested_non_usage_numbers_are_ignored(self):
        # ``thinking_tokens`` / ``web_search_requests`` / ``total_cost_usd`` /
        # ``num_turns`` are numeric but are NOT token usage; they must not leak
        # into the canonical totals (``total_tokens`` stays derived, not 1339).
        from stream_parser import parse_result_envelope

        envelope = parse_result_envelope(json.dumps(_cli_json_envelope("pong")))

        assert envelope is not None
        assert envelope.usage["total_tokens"] == 0
        assert set(envelope.usage) >= {
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        }

    def test_is_error_flag_surfaces(self):
        from stream_parser import parse_result_envelope

        envelope = parse_result_envelope(
            json.dumps(
                _cli_json_envelope(
                    "API Error: rate limited",
                    is_error=True,
                    subtype="error_during_execution",
                )
            )
        )

        assert envelope is not None
        assert envelope.is_error is True
        assert envelope.result == "API Error: rate limited"

    def test_plain_text_is_not_an_envelope(self):
        from stream_parser import parse_result_envelope

        assert parse_result_envelope("just a plain reply") is None
        assert parse_result_envelope("") is None
        assert parse_result_envelope("   ") is None

    def test_callers_own_json_reply_is_not_an_envelope(self):
        # A contract worker's reply is itself JSON (``{"verdict": ...}``). It has
        # no ``type: result`` discriminator, so it must pass through untouched.
        from stream_parser import parse_result_envelope

        reply = json.dumps({"verdict": "agree", "findings": ""})
        assert parse_result_envelope(reply) is None

    def test_stream_json_event_lines_are_not_an_envelope(self):
        # MockWorld's FakeSubprocessRunner.run_simple returns the scripted
        # stream-json event lines joined by newlines. That is a multi-object
        # stream, not one envelope — passthrough.
        from stream_parser import parse_result_envelope

        lines = "\n".join(
            [
                json.dumps({"type": "assistant", "message": {"content": []}}),
                json.dumps({"type": "result", "success": True, "exit_code": 0}),
            ]
        )
        assert parse_result_envelope(lines) is None

    def test_result_event_without_text_is_not_an_envelope(self):
        # The MockWorld fake's bare result marker carries no ``result`` string;
        # unwrapping it would erase the fake's stdout.
        from stream_parser import parse_result_envelope

        marker = json.dumps({"type": "result", "success": True, "exit_code": 0})
        assert parse_result_envelope(marker) is None

    def test_non_result_json_object_is_not_an_envelope(self):
        from stream_parser import parse_result_envelope

        assert parse_result_envelope(json.dumps({"type": "assistant"})) is None
        assert parse_result_envelope(json.dumps([1, 2, 3])) is None

    def test_envelope_without_usage_reports_unavailable(self):
        from stream_parser import parse_result_envelope

        bare = {"type": "result", "result": "ok", "is_error": False}
        envelope = parse_result_envelope(json.dumps(bare))

        assert envelope is not None
        assert envelope.result == "ok"
        assert envelope.session_id == ""
        assert envelope.usage["usage_available"] is False
        assert envelope.usage["usage_status"] == "unavailable"

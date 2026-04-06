"""Tests for TraceCollector — in-process span accumulator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from trace_collector import TraceCollector  # noqa: E402

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "stream_json" / "claude_implement_sample.jsonl"
)


def _make_config(data_root: Path) -> MagicMock:
    config = MagicMock()
    config.data_root = data_root
    return config


def _make_collector(tmp_path: Path, **overrides) -> TraceCollector:
    defaults = {
        "issue_number": 42,
        "phase": "implement",
        "source": "implementer",
        "subprocess_idx": 0,
        "run_id": 1,
        "config": _make_config(tmp_path),
        "event_bus": None,
    }
    defaults.update(overrides)
    return TraceCollector(**defaults)


class TestTraceCollectorRecord:
    def test_record_assistant_text_increments_inference(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"id": "m1", "content": [{"type": "text", "text": "hi"}]},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )
        c.record(line)
        assert c.inference_count == 1
        assert c.tokens.prompt_tokens == 10
        assert c.tokens.completion_tokens == 5

    def test_record_tool_use_appends_tool_call(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m2",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "src/foo.py"},
                        }
                    ],
                },
            }
        )
        c.record(line)
        assert len(c.tool_calls) == 1
        assert c.tool_calls[0].tool_name == "Read"
        assert c.tool_counts["Read"] == 1

    def test_record_tool_result_marks_success(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "id": "m1",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            }
                        ],
                    },
                }
            )
        )
        c.record(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "t1",
                                "content": "ok",
                            }
                        ]
                    },
                }
            )
        )
        assert c.tool_calls[0].succeeded is True

    def test_record_invalid_json_does_not_crash(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record("not valid json {{{")
        assert c.inference_count == 0

    def test_record_unknown_event_does_not_crash(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(json.dumps({"type": "weird_unknown_event_type"}))
        assert c.inference_count == 0

    def test_full_fixture_processed_correctly(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        for line in FIXTURE_PATH.read_text().strip().split("\n"):
            c.record(line)
        assert c.inference_count >= 3  # 3 assistant messages
        assert c.tool_counts.get("Read", 0) == 1
        assert c.tool_counts.get("Bash", 0) == 1
        assert c.tokens.prompt_tokens > 0
        assert c.tokens.completion_tokens > 0


class TestTraceCollectorSkillResults:
    def test_record_skill_result_appends(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record_skill_result(
            "diff-sanity",
            passed=True,
            attempts=1,
            duration_seconds=8.5,
            blocking=True,
        )
        assert len(c.skill_results) == 1
        assert c.skill_results[0].skill_name == "diff-sanity"
        assert c.skill_results[0].passed is True

    def test_multiple_skills(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record_skill_result(
            "diff-sanity", passed=True, attempts=1, duration_seconds=8.0, blocking=True
        )
        c.record_skill_result(
            "test-adequacy",
            passed=True,
            attempts=1,
            duration_seconds=6.0,
            blocking=False,
        )
        c.record_skill_result(
            "pre-quality",
            passed=False,
            attempts=2,
            duration_seconds=24.0,
            blocking=True,
        )
        assert len(c.skill_results) == 3


class TestTraceCollectorFinalize:
    def test_finalize_writes_subprocess_file(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "id": "m1",
                        "content": [{"type": "text", "text": "hi"}],
                    },
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            )
        )
        result = c.finalize(success=True)

        assert result is not None
        expected_path = (
            tmp_path / "traces" / "42" / "implement" / "run-1" / "subprocess-0.json"
        )
        assert expected_path.exists()
        loaded = json.loads(expected_path.read_text())
        assert loaded["issue_number"] == 42
        assert loaded["run_id"] == 1
        assert loaded["subprocess_idx"] == 0
        assert loaded["success"] is True

    def test_finalize_after_exception_marks_crashed(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "id": "m1",
                        "content": [{"type": "text", "text": "hi"}],
                    },
                }
            )
        )
        result = c.finalize(success=False)
        assert result is not None
        assert result.success is False
        assert result.crashed is True

    def test_finalize_empty_collection_returns_none(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        result = c.finalize(success=True)
        assert result is None


class TestBackendDetection:
    def test_claude_backend_detected_from_assistant_event(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"id": "m1", "content": [{"type": "text", "text": "x"}]},
                }
            )
        )
        assert c.backend == "claude"

    def test_codex_backend_detected_from_item_completed(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "ok"},
                }
            )
        )
        assert c.backend == "codex"

    def test_pi_backend_detected_from_message_update(self, tmp_path: Path):
        c = _make_collector(tmp_path)
        c.record(
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "x"},
                }
            )
        )
        assert c.backend == "pi"

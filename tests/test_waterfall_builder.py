"""Tests for waterfall_builder (spec §4.11 point 1 aggregator)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_routes._waterfall_builder import (
    PHASE_ORDER,
    _phase_for_source,
    build_waterfall,
)


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108
    cfg.repo = "o/r"
    return cfg


def _write_trace(
    config: MagicMock, issue: int, phase: str, run_id: int, idx: int, payload: dict
) -> None:
    run_dir = config.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"subprocess-{idx}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_inference(config: MagicMock, **fields) -> None:
    inf_dir = config.data_root / "metrics" / "prompt"
    inf_dir.mkdir(parents=True, exist_ok=True)
    path = inf_dir / "inferences.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: MagicMock, loop: str, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    started_at = fields.get("started_at", "2026-04-22T10:00:00+00:00")
    safe = started_at.replace(":", "")
    (d / f"run-{safe}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_phase_order_is_canonical_seven() -> None:
    assert PHASE_ORDER == (
        "triage",
        "discover",
        "shape",
        "plan",
        "implement",
        "review",
        "merge",
    )


def test_phase_for_source_collapses_offpipeline() -> None:
    assert _phase_for_source("hitl") == "review"
    assert _phase_for_source("decomposition") == "triage"
    assert _phase_for_source("planner") == "plan"
    assert _phase_for_source("unknown_xyz") == "unknown_xyz"


def test_builds_empty_waterfall_with_all_phases_missing(config) -> None:
    issue_meta = {"number": 1234, "title": "t", "labels": []}
    result = build_waterfall(config, issue=1234, issue_meta=issue_meta)
    assert result["issue"] == 1234
    assert result["title"] == "t"
    assert result["labels"] == []
    assert result["phases"] == []
    assert set(result["missing_phases"]) == set(PHASE_ORDER)
    assert result["total"]["cost_usd"] == 0.0


def test_llm_action_sourced_from_prompt_telemetry(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=1000,
        output_tokens=500,
        cache_creation_input_tokens=100,
        cache_read_input_tokens=200,
        duration_seconds=12.3,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.042
    result = build_waterfall(
        config,
        issue=1234,
        issue_meta={"number": 1234, "title": "t", "labels": []},
        pricing=pricing,
    )
    phases = {p["phase"]: p for p in result["phases"]}
    assert "implement" in phases
    actions = phases["implement"]["actions"]
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "llm"
    assert a["model"] == "claude-sonnet-4-6"
    assert a["tokens_in"] == 1000
    assert a["tokens_out"] == 500
    assert a["cost_usd"] == 0.042
    pricing.estimate_cost.assert_called_once_with(
        "claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_write_tokens=100,
        cache_read_tokens=200,
    )


def test_skill_action_from_subprocess_trace_skill_results(config) -> None:
    _write_trace(
        config,
        issue=1234,
        phase="review",
        run_id=1,
        idx=1,
        payload={
            "issue_number": 1234,
            "phase": "review",
            "source": "reviewer",
            "run_id": 1,
            "subprocess_idx": 1,
            "backend": "claude",
            "started_at": "2026-04-22T11:00:00+00:00",
            "ended_at": "2026-04-22T11:00:30+00:00",
            "success": True,
            "tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_hit_rate": 0.0,
            },
            "tools": {"tool_counts": {}, "tool_errors": {}, "total_invocations": 0},
            "tool_calls": [],
            "skill_results": [
                {
                    "skill_name": "diff-sanity",
                    "passed": True,
                    "attempts": 1,
                    "duration_seconds": 3.5,
                    "blocking": True,
                },
            ],
            "inference_count": 0,
            "turn_count": 0,
        },
    )
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []}
    )
    phases = {p["phase"]: p for p in result["phases"]}
    actions = phases["review"]["actions"]
    skill = next(a for a in actions if a["kind"] == "skill")
    assert skill["skill"] == "diff-sanity"
    assert skill["duration_ms"] == 3500


def test_subprocess_action_from_bash_tool_calls(config) -> None:
    _write_trace(
        config,
        issue=1234,
        phase="implement",
        run_id=1,
        idx=1,
        payload={
            "issue_number": 1234,
            "phase": "implement",
            "source": "implementer",
            "run_id": 1,
            "subprocess_idx": 1,
            "backend": "claude",
            "started_at": "2026-04-22T10:00:00+00:00",
            "ended_at": "2026-04-22T10:05:00+00:00",
            "success": True,
            "tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_hit_rate": 0.0,
            },
            "tools": {
                "tool_counts": {"Bash": 2},
                "tool_errors": {},
                "total_invocations": 2,
            },
            "tool_calls": [
                {
                    "tool_name": "Bash",
                    "started_at": "2026-04-22T10:01:00+00:00",
                    "duration_ms": 800,
                    "input_summary": "pytest tests/test_x.py",
                    "succeeded": True,
                    "tool_use_id": "t1",
                },
                {
                    "tool_name": "Bash",
                    "started_at": "2026-04-22T10:02:00+00:00",
                    "duration_ms": 120,
                    "input_summary": "git status",
                    "succeeded": True,
                    "tool_use_id": "t2",
                },
            ],
            "skill_results": [],
            "inference_count": 0,
            "turn_count": 0,
        },
    )
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []}
    )
    phases = {p["phase"]: p for p in result["phases"]}
    sp = [a for a in phases["implement"]["actions"] if a["kind"] == "subprocess"]
    assert len(sp) == 2
    assert sp[0]["command"].startswith("pytest")
    assert sp[0]["duration_ms"] == 800
    assert sp[1]["command"] == "git status"


def test_loop_attached_only_when_in_issue_window(config) -> None:
    _write_loop_trace(
        config,
        loop="CorpusLearningLoop",
        command=["gh", "api", "search/issues"],
        exit_code=0,
        duration_ms=2200,
        started_at="2026-04-22T10:30:00+00:00",  # inside window
    )
    _write_loop_trace(
        config,
        loop="CorpusLearningLoop",
        command=["x"],
        exit_code=0,
        duration_ms=1,
        started_at="2026-04-25T10:30:00+00:00",  # after merge — excluded
    )
    issue_meta = {
        "number": 1234,
        "title": "t",
        "labels": [],
        "first_seen": "2026-04-22T10:00:00+00:00",
        "merged_at": "2026-04-22T11:00:00+00:00",
    }
    result = build_waterfall(config, issue=1234, issue_meta=issue_meta)
    loops = [a for p in result["phases"] for a in p["actions"] if a["kind"] == "loop"]
    assert len(loops) == 1
    assert loops[0]["duration_ms"] == 2200


def test_ordering_total_and_missing_phases(config) -> None:
    # Two impl inferences (out-of-order write) + one reviewer inference.
    _write_inference(
        config,
        timestamp="2026-04-22T10:05:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=20,
        duration_seconds=5,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T10:02:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=20,
        output_tokens=10,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="reviewer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=200,
        output_tokens=80,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=40,
        duration_seconds=7,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.side_effect = [0.01, 0.005, 0.02]
    result = build_waterfall(
        config,
        issue=1234,
        issue_meta={"number": 1234, "title": "t", "labels": []},
        pricing=pricing,
    )
    # Ordering within phase
    impl = next(p for p in result["phases"] if p["phase"] == "implement")
    assert [a["started_at"] for a in impl["actions"]] == sorted(
        a["started_at"] for a in impl["actions"]
    )
    # Total rollup across phases
    assert result["total"]["tokens_in"] == 320
    assert result["total"]["tokens_out"] == 140
    assert result["total"]["cache_read_tokens"] == 60
    assert result["total"]["cache_write_tokens"] == 10
    assert result["total"]["cost_usd"] == pytest.approx(0.035)
    # Missing phases: everything except implement + review
    assert set(result["missing_phases"]) == set(PHASE_ORDER) - {"implement", "review"}


def test_unknown_model_yields_zero_cost_no_crash(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="made-up-model-xyz",
        issue_number=1234,
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = None
    result = build_waterfall(
        config,
        issue=1234,
        issue_meta={"number": 1234, "title": "t", "labels": []},
        pricing=pricing,
    )
    impl = next(p for p in result["phases"] if p["phase"] == "implement")
    # Unknown-model cost is 0.0 (not None) in the rollup; action keeps model id.
    assert impl["cost_usd"] == 0.0
    assert impl["actions"][0]["cost_usd"] == 0.0

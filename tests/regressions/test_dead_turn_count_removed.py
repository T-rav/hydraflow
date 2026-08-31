"""`turn_count` / `total_turns` never held a value — remove, don't invent one.

`TraceCollector.turn_count` was initialised to 0, read into every
`SubprocessTrace`, and never incremented anywhere. `trace_rollup` summed it
into `TraceSpanStats.total_turns`, which the diagnostics API serves. Every
trace ever written reported zero turns.

There is no unambiguous "turn" for the Claude backend in the handled event
set, and `inference_count` already counts model work and IS populated. So the
field is removed rather than back-filled with an invented definition. Traces
already on disk keep the key; Pydantic ignores it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from models import SubprocessTrace, TraceSpanStats  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402
from trace_rollup import write_phase_rollup  # noqa: E402

_LEGACY_TRACE = {
    "issue_number": 5,
    "phase": "implement",
    "source": "implementer",
    "run_id": 1,
    "subprocess_idx": 0,
    "backend": "claude",
    "started_at": "2026-08-31T00:00:00+00:00",
    "ended_at": "2026-08-31T00:01:00+00:00",
    "success": True,
    "crashed": False,
    "error": None,
    "tokens": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_hit_rate": 0.0,
    },
    "tools": {"tool_counts": {"Bash": 1}, "tool_errors": {}, "total_invocations": 1},
    "tool_calls": [],
    "skill_results": [],
    "turn_count": 0,
    "inference_count": 3,
}


class TestTheDeadFieldIsGone:
    def test_subprocess_trace_no_longer_declares_turn_count(self):
        assert "turn_count" not in SubprocessTrace.model_fields

    def test_span_stats_no_longer_declares_total_turns(self):
        assert "total_turns" not in TraceSpanStats.model_fields

    def test_no_trace_module_still_references_it(self):
        """Scoped to the trace domain, derived from who imports the models.

        `shape_runner` has its own unrelated `turn_count` local
        (``len(conversation.turns)``) that is real and populated — a repo-wide
        grep would flag it and make this guard wrong, not strict.
        """
        src = Path(__file__).parent.parent.parent / "src"
        trace_modules = [
            path
            for path in src.rglob("*.py")
            if any(
                name in path.read_text(encoding="utf-8", errors="replace")
                for name in ("SubprocessTrace", "TraceSpanStats")
            )
        ]
        assert trace_modules, "derivation found no trace modules — guard is vacuous"

        offenders = [
            f"{path.relative_to(src)}:{i}"
            for path in trace_modules
            for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            )
            if "turn_count" in line or "total_turns" in line
        ]

        assert not offenders, f"dead field still referenced: {offenders}"


class TestTracesAlreadyOnDiskStillWork:
    def test_a_legacy_trace_carrying_turn_count_still_parses(self):
        trace = SubprocessTrace.model_validate(_LEGACY_TRACE)

        assert trace.inference_count == 3

    def test_rollup_over_legacy_traces_still_produces_a_summary(self, tmp_path: Path):
        config = ConfigFactory.create()
        config.data_root = tmp_path
        run_dir = tmp_path / "traces" / "5" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "subprocess-0.json").write_text(json.dumps(_LEGACY_TRACE))

        summary = write_phase_rollup(
            config=config, issue_number=5, phase="implement", run_id=1
        )

        assert summary is not None
        assert summary.spans.total_inference_calls == 3

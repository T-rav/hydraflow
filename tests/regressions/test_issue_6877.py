"""Regression test for issue #6877.

Bug: ``_append_factory_metric`` writes to ``factory_metrics.jsonl`` with a
plain ``with open(path, "a") as f: f.write(json.dumps(event) + "\\n")``
pattern.  If the write fails after outputting partial data (e.g., disk-full
``OSError``), the JSONL file is left with an incomplete line — no trailing
newline.  Because the next successful append opens the file in ``"a"`` mode,
its data is concatenated *onto the corrupted partial line*, merging two
events into a single invalid JSON line.  ``load_metrics`` silently skips the
corrupted line, causing **both** the failed event and the subsequent valid
event to vanish from the diagnostics dashboard with no error.

Expected behaviour after fix:
  - A partial write failure must not leave a corrupted line in the file.
  - Subsequent successful writes must not be lost due to a prior failure.
  - The fix should use atomic writes (temp file + rename), or truncate /
    pad on failure, so each line boundary is always preserved.

These tests intentionally assert the *correct* behaviour, so they are RED
against the current (buggy) code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from factory_metrics import load_metrics
from models import (
    SubprocessTrace,
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)
from trace_rollup import _append_factory_metric


def _make_summary(*, issue_number: int = 42, phase: str = "implement") -> TraceSummary:
    return TraceSummary(
        issue_number=issue_number,
        phase=phase,
        harvested_at="2026-04-10T00:00:00+00:00",
        trace_ids=[],
        spans=TraceSpanStats(
            total_spans=1,
            total_turns=1,
            total_inference_calls=1,
            duration_seconds=10.0,
        ),
        tokens=TraceTokenStats(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(
            tool_counts={},
            tool_errors={},
            total_invocations=0,
        ),
        skills=TraceSkillProfile(
            skill_counts={},
            subagent_counts={},
            total_skills=0,
            total_subagents=0,
        ),
    )


def _make_trace() -> SubprocessTrace:
    return SubprocessTrace(
        issue_number=42,
        phase="implement",
        source="claude",
        run_id=1,
        subprocess_idx=0,
        backend="claude",
        started_at="2026-04-10T00:00:00+00:00",
        success=True,
        tokens=TraceTokenStats(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(
            tool_counts={},
            tool_errors={},
            total_invocations=0,
        ),
    )


class TestFactoryMetricJSONLCorruption:
    """Issue #6877 — partial write corruption cascades in factory_metrics.jsonl."""

    @pytest.mark.xfail(reason="Regression for issue #6877 — fix not yet landed", strict=False)
    def test_partial_write_cascades_to_corrupt_subsequent_event(self, config) -> None:
        """A partial write (from a prior disk-full failure) without a trailing
        newline causes the NEXT successful ``_append_factory_metric`` call to
        merge its data with the corrupted line, silently losing both events.

        After the fix, ``_append_factory_metric`` should ensure each line
        starts on its own newline boundary (e.g., atomic temp-file writes or
        a leading-newline guard) so a prior failure never cascades.
        """
        metrics_path = config.factory_metrics_path
        metrics_path.parent.mkdir(parents=True, exist_ok=True)

        summary = _make_summary()
        traces = [_make_trace()]

        # Event 1: successful write — establishes a known-good baseline.
        _append_factory_metric(config, summary, traces, [])

        # Simulate the aftermath of a partial write failure: truncated JSON
        # with no trailing newline, exactly what the JSONL file would contain
        # after an OSError interrupts f.write() inside _append_factory_metric.
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write('{"timestamp": "2026-04-10", "issue": 99, "phase": "review"')
            # ↑ No closing brace, no newline — simulates disk-full mid-write.

        # Event 3: a new successful call to _append_factory_metric.
        # Because the file currently ends without a newline, the new JSON
        # object is concatenated directly after the partial data from the
        # failed write, creating one long garbage line.
        _append_factory_metric(config, summary, traces, [])

        # Read back all events via the diagnostics dashboard reader.
        events = load_metrics(metrics_path)

        # We expect at least events 1 and 3 to be recoverable.
        # Currently only event 1 survives — event 3 is merged with the
        # partial line from the simulated failure, corrupting both.
        assert len(events) >= 2, (
            f"Expected at least 2 readable events but got {len(events)}. "
            f"Bug #6877: a partial write failure in factory_metrics.jsonl "
            f"cascades to corrupt the next valid event written by "
            f"_append_factory_metric. The diagnostics dashboard silently "
            f"loses data."
        )

    @pytest.mark.xfail(reason="Regression for issue #6877 — fix not yet landed", strict=False)
    def test_all_lines_valid_json_after_partial_write(self, config) -> None:
        """After a write failure, every line in the JSONL file must be
        parseable JSON.  No corrupted partial lines should remain.

        Currently, a partial write leaves an incomplete JSON fragment that
        ``load_metrics`` silently skips — invisible data loss.
        """
        metrics_path = config.factory_metrics_path
        metrics_path.parent.mkdir(parents=True, exist_ok=True)

        summary = _make_summary()
        traces = [_make_trace()]

        # Write one valid event.
        _append_factory_metric(config, summary, traces, [])

        # Inject a partial (corrupted) line — simulating the result of
        # a failed write that was not cleaned up.
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write('{"timestamp": "2026-04-10", "issue": 99')

        # Write another valid event after the corruption.
        _append_factory_metric(config, summary, traces, [])

        # Every non-empty line should be valid JSON.
        content = metrics_path.read_text(encoding="utf-8")
        lines = [line for line in content.split("\n") if line.strip()]
        for i, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                pytest.fail(
                    f"Line {i + 1} of factory_metrics.jsonl is corrupted: "
                    f"{line!r}. Bug #6877: _append_factory_metric does not "
                    f"protect against partial-write corruption cascading to "
                    f"subsequent events."
                )

"""Regression test for issue #6470.

compute_trend_metrics() in health_monitor_loop.py uses four silent
``except Exception: pass`` blocks when parsing JSONL metric files.
If a file has a single malformed line or a transient read error, the
*entire* metric is silently zeroed -- avg_memory_score, stale_item_count,
surprise_rate, hitl_escalation_rate all return 0 with no log output.

These tests verify that when parse errors occur, the code either:
  - Logs a warning/debug message (so operators can detect the problem), OR
  - Returns a distinguishable sentinel (not a silent zero).

Currently all four tests FAIL because the except blocks use bare ``pass``.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from health_monitor_loop import compute_trend_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Bug 1 (lines 195-206): malformed item_scores.json silently zeros
#         avg_memory_score and stale_item_count
# ---------------------------------------------------------------------------


class TestMalformedScoresFileLogsWarning:
    """A corrupt item_scores.json should produce a log warning, not silence."""

    def test_corrupt_scores_json_emits_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        # Write valid outcomes so we know the function runs
        _write_jsonl(outcomes, [{"outcome": "success"}])
        # Write malformed JSON to scores file
        _write_text(scores, "THIS IS NOT JSON {{{")
        _write_jsonl(failures, [])

        with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
            metrics = compute_trend_metrics(outcomes, scores, failures)

        # The bug: avg_memory_score is silently 0.0 with no log output.
        # After fix, there should be a warning-level log message.
        warning_or_above = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and ("score" in r.message.lower() or "parse" in r.message.lower())
        ]
        assert warning_or_above, (
            "Expected a WARNING log when item_scores.json is malformed, "
            f"but got no relevant warnings. avg_memory_score={metrics.avg_memory_score} "
            "(silently zeroed)"
        )


# ---------------------------------------------------------------------------
# Bug 2 (lines 213-227): malformed line in harness_failures.jsonl silently
#         skipped with no log — surprise_rate and hitl_escalation_rate
#         computed on truncated data
# ---------------------------------------------------------------------------


class TestMalformedFailureLineLogsDebug:
    """A corrupt line in harness_failures.jsonl should log, not silently skip."""

    def test_corrupt_failure_line_emits_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        _write_jsonl(outcomes, [])
        # No scores file needed
        # Write failures with a mix of valid and malformed lines
        content = (
            json.dumps({"category": "hitl_escalation"})
            + "\n"
            + "NOT VALID JSON\n"
            + json.dumps({"category": "review_rejection"})
            + "\n"
        )
        _write_text(failures, content)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
            compute_trend_metrics(outcomes, scores, failures)

        # The bug: the malformed line is silently skipped, total_failures=3
        # but only 2 lines parse, so rates are computed on wrong denominator.
        # total_failures counts raw lines (3) but only 2 parsed, giving
        # hitl_escalation_rate = 1/3 instead of 1/2.
        # After fix, the bad line should be logged at debug level.
        any_parse_log = [
            r
            for r in caplog.records
            if r.levelno >= logging.DEBUG
            and (
                "parse" in r.message.lower()
                or "skip" in r.message.lower()
                or "malformed" in r.message.lower()
                or "failure record" in r.message.lower()
            )
        ]
        assert any_parse_log, (
            "Expected a DEBUG log when a harness_failures.jsonl line is malformed, "
            "but got no relevant log messages. The bad line was silently swallowed."
        )


# ---------------------------------------------------------------------------
# Bug 3 (lines 348-354): detect_knowledge_gaps failure silently zeros
#         gap_count with no log
# ---------------------------------------------------------------------------
# This runs inside HealthMonitorLoop._do_work, which requires more setup.
# We test indirectly by verifying the except block pattern.


class TestKnowledgeGapSilentZero:
    """detect_knowledge_gaps failure should log, not silently zero gap_count."""

    def test_import_error_in_knowledge_gaps_emits_log(self) -> None:
        """Simulate the except block by importing the module and checking
        that a failure in detect_knowledge_gaps is logged.

        Since detect_knowledge_gaps is called inside _do_work (an async
        method requiring full loop setup), we verify the pattern by
        inspecting that the except block at line ~353 uses ``pass`` with
        no logging -- this is the direct evidence of the bug.
        """
        import ast
        import inspect
        import textwrap

        from health_monitor_loop import HealthMonitorLoop

        source = textwrap.dedent(inspect.getsource(HealthMonitorLoop._do_work))
        tree = ast.parse(source)

        # Find all except handlers that catch Exception and have only Pass
        silent_except_blocks: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and (
                node.type is not None
                and isinstance(node.type, ast.Name)
                and node.type.id == "Exception"
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                silent_except_blocks.append(node.lineno)

        assert not silent_except_blocks, (
            f"HealthMonitorLoop._do_work has silent `except Exception: pass` blocks "
            f"at relative source lines {silent_except_blocks}. "
            "These should log at debug/warning level instead of silently swallowing errors."
        )


# ---------------------------------------------------------------------------
# Bug 4 (lines 513-523): HITL recommendations JSONL read failure silently
#         zeros hitl_recommendations_count
# ---------------------------------------------------------------------------


class TestHitlRecommendationsCountSilentZero:
    """HITL recommendations parse failure should log, not silently zero."""

    def test_hitl_recommendations_silent_except_exists(self) -> None:
        """Verify that the except block around HITL recommendations read
        in _do_work still uses silent ``pass`` (proving the bug exists).
        """
        import ast
        import inspect
        import textwrap

        from health_monitor_loop import HealthMonitorLoop

        source = textwrap.dedent(inspect.getsource(HealthMonitorLoop._do_work))
        tree = ast.parse(source)

        # Collect all silent `except Exception: pass` blocks
        silent_blocks: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and (
                node.type is not None
                and isinstance(node.type, ast.Name)
                and node.type.id == "Exception"
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                silent_blocks.append(node.lineno)

        assert not silent_blocks, (
            f"HealthMonitorLoop._do_work contains {len(silent_blocks)} silent "
            f"`except Exception: pass` block(s) at relative source lines {silent_blocks}. "
            "Each should log at an appropriate level (debug or warning)."
        )


# ---------------------------------------------------------------------------
# Integration: compute_trend_metrics with entirely malformed scores file
#   returns 0.0 for avg_memory_score with NO indication of error
# ---------------------------------------------------------------------------


class TestSilentZeroIsIndistinguishableFromRealZero:
    """The core problem: a parse error produces the same output as 'no data'."""

    def test_malformed_scores_indistinguishable_from_empty(
        self, tmp_path: Path
    ) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        scores_bad = tmp_path / "bad_scores.json"
        scores_empty = tmp_path / "empty_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        _write_jsonl(outcomes, [{"outcome": "success"}])
        _write_jsonl(failures, [])

        # Case 1: malformed scores
        _write_text(scores_bad, "CORRUPT DATA {{{")
        metrics_bad = compute_trend_metrics(outcomes, scores_bad, failures)

        # Case 2: legitimately empty scores (file doesn't exist)
        metrics_empty = compute_trend_metrics(outcomes, scores_empty, failures)

        # The bug: both return avg_memory_score=0.0 -- they are
        # indistinguishable. A caller cannot tell "no data" from "parse error".
        # This assertion documents the bug: we WANT them to be distinguishable.
        assert (
            metrics_bad.avg_memory_score != metrics_empty.avg_memory_score
            or metrics_bad.stale_item_count != metrics_empty.stale_item_count
        ), (
            "Malformed scores file produces the same metrics as a missing file "
            f"(avg_memory_score={metrics_bad.avg_memory_score}, "
            f"stale_item_count={metrics_bad.stale_item_count}). "
            "Parse errors are silently indistinguishable from 'no data'."
        )

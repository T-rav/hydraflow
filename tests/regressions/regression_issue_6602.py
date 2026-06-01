"""Regression test for issue #6602.

``health_monitor_loop.py`` has multiple ``except Exception: pass`` blocks
(lines 205–206, 226–227, 353–354, 522–523) wrapping metric computation from
JSONL files.  When any of these fail (corrupt JSON, missing field, unexpected
type), the metric variable stays at its zero-initialized default value.

The ``TrendMetrics`` returned contains ``0.0`` for all affected fields, which
looks like healthy/nominal data to consumers rather than "unknown/error".
This masks real degradation in ``first_pass_rate``, ``avg_memory_score``,
and HITL counts.

These tests feed corrupt data into ``compute_trend_metrics`` and assert that
the result is distinguishable from a legitimate computation.  They will FAIL
(RED) until the silent ``pass`` blocks are replaced with proper error
signaling (e.g., ``Optional[float]`` fields or a ``metrics_computed`` flag).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from health_monitor_loop import compute_trend_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# Tests — corrupt data must be distinguishable from healthy zeros
# ---------------------------------------------------------------------------


class TestIssue6602SilentExceptPass:
    """Corrupt input must not produce metrics indistinguishable from healthy."""

    @pytest.mark.xfail(reason="Regression for issue #6602 — fix not yet landed", strict=False)
    def test_corrupt_scores_json_not_silently_zero(self, tmp_path: Path) -> None:
        """Corrupt item_scores.json should NOT produce avg_memory_score == 0.0.

        When the JSON file is malformed, the except-pass block (line 205–206)
        swallows the error and avg_memory_score stays at its 0.0 default.
        A caller cannot distinguish this from a legitimate "all scores are 0".

        The fix should either:
        - Set avg_memory_score to None (Optional[float]), or
        - Raise an exception, or
        - Set a flag indicating computation failure.

        This test FAILS (RED) because the current code returns 0.0.
        """
        scores_path = tmp_path / "item_scores.json"
        _write_text(scores_path, "THIS IS NOT VALID JSON {{{")

        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            scores_path,
            tmp_path / "harness_failures.jsonl",
        )

        # The metric should signal failure — not silently be 0.0
        # Currently returns 0.0, which is indistinguishable from healthy data
        assert metrics.avg_memory_score is None, (
            f"Corrupt scores file produced avg_memory_score={metrics.avg_memory_score}; "
            "expected None to signal computation failure, got silent 0.0 instead"
        )

    @pytest.mark.xfail(reason="Regression for issue #6602 — fix not yet landed", strict=False)
    def test_corrupt_scores_json_stale_count_not_silently_zero(
        self, tmp_path: Path
    ) -> None:
        """Corrupt item_scores.json should NOT produce stale_item_count == 0.

        Same except-pass block — stale_item_count stays at 0, which looks
        like "no stale items" rather than "failed to compute".
        """
        scores_path = tmp_path / "item_scores.json"
        _write_text(scores_path, '{"key": "not-a-dict-of-score-objects"}')

        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            scores_path,
            tmp_path / "harness_failures.jsonl",
        )

        # The score values will fail float() conversion or .get() won't work
        # on a string value — the except-pass swallows it, returning 0
        assert metrics.avg_memory_score is None or metrics.stale_item_count is None, (
            "Corrupt scores data produced nominal-looking metrics; "
            "callers cannot distinguish this from 'healthy zero'"
        )

    @pytest.mark.xfail(reason="Regression for issue #6602 — fix not yet landed", strict=False)
    def test_corrupt_failure_lines_mask_hitl_escalation(self, tmp_path: Path) -> None:
        """Corrupt lines in harness_failures.jsonl silently zero out HITL counts.

        Lines 226–227: the inner except-pass on per-line JSON parsing means
        corrupt lines are silently skipped.  If ALL lines are corrupt,
        hitl_count and surprise_count stay at 0 but total_failures is 0 too
        (since the outer try succeeded but the inner loop counted nothing).

        With a mix of valid and corrupt lines, total_failures counts all
        lines (including corrupt ones) but the category counts only reflect
        valid lines — the rates are wrong.
        """
        failures_path = tmp_path / "harness_failures.jsonl"
        # Mix of valid HITL escalation lines and corrupt lines
        content = (
            '{"category": "hitl_escalation", "ts": "2026-01-01"}\n'
            "NOT VALID JSON\n"
            '{"category": "hitl_escalation", "ts": "2026-01-02"}\n'
            "ALSO CORRUPT\n"
            '{"category": "review_rejection", "ts": "2026-01-03"}\n'
        )
        _write_text(failures_path, content)

        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            failures_path,
        )

        # total_failures = 5 (all lines), but only 3 lines parse:
        #   hitl_count=2, surprise_count=1
        # So hitl_escalation_rate = 2/5 = 0.4, surprise_rate = 1/5 = 0.2
        # The correct rates (excluding corrupt lines) would be 2/3 and 1/3.
        # The except-pass silently distorts the rate denominators.
        #
        # At minimum, corrupt lines should be logged as warnings.
        assert metrics.hitl_escalation_rate == pytest.approx(2 / 3), (
            f"hitl_escalation_rate={metrics.hitl_escalation_rate}; corrupt lines "
            "silently inflated the denominator (total_failures counts them but "
            "they contribute no category matches)"
        )

    @pytest.mark.xfail(reason="Regression for issue #6602 — fix not yet landed", strict=False)
    def test_corrupt_scores_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt score data must emit a warning log, not silently pass.

        The except-pass at lines 205–206 swallows ALL exceptions with no
        logging.  The fix should at minimum log a warning so operators can
        see that metric computation failed.
        """
        scores_path = tmp_path / "item_scores.json"
        _write_text(scores_path, "CORRUPT")

        with caplog.at_level(logging.WARNING, logger="hydraflow.health_monitor_loop"):
            compute_trend_metrics(
                tmp_path / "outcomes.jsonl",
                scores_path,
                tmp_path / "harness_failures.jsonl",
            )

        warning_messages = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert warning_messages, (
            "No warning logged for corrupt item_scores.json — the except-pass "
            "silently swallowed the error with no operator visibility"
        )

    @pytest.mark.xfail(reason="Regression for issue #6602 — fix not yet landed", strict=False)
    def test_corrupt_data_indistinguishable_from_empty(self, tmp_path: Path) -> None:
        """Corrupt data and missing data produce identical TrendMetrics.

        This is the core problem: an operator looking at the metrics cannot
        tell whether the pipeline is healthy (no data yet) or whether the
        metric computation is broken (corrupt data).
        """
        # Compute metrics with NO data files (all missing)
        metrics_empty = compute_trend_metrics(
            tmp_path / "missing_outcomes.jsonl",
            tmp_path / "missing_scores.json",
            tmp_path / "missing_failures.jsonl",
        )

        # Compute metrics with ALL CORRUPT data files
        corrupt_dir = tmp_path / "corrupt"
        corrupt_dir.mkdir()

        outcomes_path = corrupt_dir / "outcomes.jsonl"
        _write_text(outcomes_path, "NOT JSON\nALSO NOT JSON\n")

        scores_path = corrupt_dir / "item_scores.json"
        _write_text(scores_path, "CORRUPT SCORES FILE")

        failures_path = corrupt_dir / "harness_failures.jsonl"
        _write_text(failures_path, "CORRUPT\nCORRUPT\n")

        metrics_corrupt = compute_trend_metrics(
            outcomes_path,
            scores_path,
            failures_path,
        )

        # These should NOT be identical — corrupt data should be
        # distinguishable from missing data
        all_same = (
            metrics_empty.first_pass_rate == metrics_corrupt.first_pass_rate
            and metrics_empty.avg_memory_score == metrics_corrupt.avg_memory_score
            and metrics_empty.surprise_rate == metrics_corrupt.surprise_rate
            and metrics_empty.hitl_escalation_rate
            == metrics_corrupt.hitl_escalation_rate
            and metrics_empty.stale_item_count == metrics_corrupt.stale_item_count
        )

        assert not all_same, (
            "Corrupt data produced metrics identical to missing data: "
            f"first_pass_rate={metrics_corrupt.first_pass_rate}, "
            f"avg_memory_score={metrics_corrupt.avg_memory_score}, "
            f"surprise_rate={metrics_corrupt.surprise_rate}, "
            f"hitl_escalation_rate={metrics_corrupt.hitl_escalation_rate}. "
            "Callers cannot distinguish 'broken computation' from 'healthy/no data'"
        )

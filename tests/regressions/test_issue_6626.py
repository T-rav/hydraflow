"""Regression test for issue #6626.

Bug: compute_trend_metrics() silently passes on malformed JSON lines and
file-read errors — metric computation returns zeros without any logging.

The three except-pass blocks (lines 182, 184, 205-206) swallow errors without
emitting any log message, meaning:
- OSError on file read → returns 0% first_pass_rate with no warning
- Malformed JSONL lines → silently excluded from success rate calculation
- Corrupt item_scores.json → avg_memory_score silently returns 0.0

These tests assert that the function SHOULD log when encountering these errors.
They will FAIL (RED) against the current code because the current code uses
bare ``pass`` with no logging.
"""

from __future__ import annotations

import pytest

import logging
from pathlib import Path
from unittest.mock import patch

from health_monitor_loop import compute_trend_metrics


class TestIssue6626SilentPassOnErrors:
    """compute_trend_metrics should log when skipping malformed data or hitting OS errors."""

    # --- outcomes.jsonl: OSError on file read should log a warning ---

    @pytest.mark.xfail(reason="Regression for issue #6626 — fix not yet landed", strict=False)
    def test_outcomes_oserror_logs_warning(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """An OSError reading outcomes.jsonl should emit a warning log, not pass silently.

        Currently FAILS because the except OSError block at line 184 does ``pass``.
        """
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        # Create files so .exists() returns True
        outcomes.write_text('{"outcome": "success"}\n')
        scores.write_text("{}")
        failures.write_text("")

        # Patch read_text to raise OSError after .exists() passes
        original_read_text = Path.read_text

        def _exploding_read_text(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
            if self == outcomes:
                raise OSError("Permission denied")
            return original_read_text(self, *args, **kwargs)

        with (
            patch.object(Path, "read_text", _exploding_read_text),
            caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"),
        ):
            result = compute_trend_metrics(outcomes, scores, failures)

        # The function returns zeros — that's the observed (buggy) behavior
        assert result.first_pass_rate == 0.0
        assert result.total_outcomes == 0

        # BUG: no warning is logged about the OSError.
        # The fix should log at WARNING level when a file read fails.
        warning_messages = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(
            "outcomes" in msg.lower() or "permission" in msg.lower()
            for msg in warning_messages
        ), (
            f"Expected a WARNING-level log about the outcomes.jsonl read failure, "
            f"got: {warning_messages}"
        )

    # --- outcomes.jsonl: malformed lines should log at debug level ---

    @pytest.mark.xfail(reason="Regression for issue #6626 — fix not yet landed", strict=False)
    def test_malformed_outcome_lines_log_debug(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """Malformed JSONL lines in outcomes.jsonl should log at DEBUG, not pass silently.

        Currently FAILS because the except Exception block at line 182 does ``pass``.
        """
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        outcomes.write_text(
            '{"outcome": "success"}\n'
            "NOT VALID JSON\n"
            '{"outcome": "failure"}\n'
            "{truncated\n"
        )
        scores.write_text("{}")
        failures.write_text("")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
            result = compute_trend_metrics(outcomes, scores, failures)

        # Only 2 of 4 lines are valid — the function counts them correctly
        assert result.total_outcomes == 2
        assert result.first_pass_rate == 0.5

        # BUG: the 2 malformed lines are skipped without any log message.
        # The fix should log at DEBUG level for each skipped line.
        debug_messages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any(
            "skip" in msg.lower() or "malformed" in msg.lower()
            for msg in debug_messages
        ), (
            f"Expected DEBUG-level log about skipped malformed lines, "
            f"got: {debug_messages}"
        )

    # --- item_scores.json: parse error should log, not pass silently ---

    @pytest.mark.xfail(reason="Regression for issue #6626 — fix not yet landed", strict=False)
    def test_corrupt_item_scores_logs_warning(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """A corrupt item_scores.json should emit a log, not silently return 0.0.

        Currently FAILS because the except Exception block at line 205 does ``pass``.
        """
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        outcomes.write_text("")
        scores.write_text("NOT VALID JSON AT ALL")
        failures.write_text("")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
            result = compute_trend_metrics(outcomes, scores, failures)

        # avg_memory_score defaults to 0.0 when parse fails
        assert result.avg_memory_score == 0.0

        # BUG: no log emitted about the parse failure.
        log_messages = [r.message for r in caplog.records]
        assert any(
            "score" in msg.lower()
            or "item_scores" in msg.lower()
            or "json" in msg.lower()
            for msg in log_messages
        ), (
            f"Expected a log message about item_scores.json parse failure, "
            f"got: {log_messages}"
        )

    # --- harness_failures.jsonl: OSError should log a warning ---

    @pytest.mark.xfail(reason="Regression for issue #6626 — fix not yet landed", strict=False)
    def test_failures_oserror_logs_warning(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """An OSError reading harness_failures.jsonl should emit a warning log.

        Currently FAILS because the except OSError at line 228-229 does ``pass``.
        """
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        outcomes.write_text("")
        scores.write_text("{}")
        failures.write_text('{"category": "hitl_escalation"}\n')

        original_read_text = Path.read_text

        def _exploding_read_text(self: Path, *args, **kwargs):  # noqa: ANN002, ANN003
            if self == failures:
                raise OSError("Disk error")
            return original_read_text(self, *args, **kwargs)

        with (
            patch.object(Path, "read_text", _exploding_read_text),
            caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"),
        ):
            result = compute_trend_metrics(outcomes, scores, failures)

        # Returns zeros because the file couldn't be read
        assert result.surprise_rate == 0.0
        assert result.hitl_escalation_rate == 0.0

        # BUG: no warning logged about the file read failure.
        warning_messages = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(
            "failure" in msg.lower() or "disk" in msg.lower()
            for msg in warning_messages
        ), (
            f"Expected a WARNING-level log about harness_failures.jsonl read failure, "
            f"got: {warning_messages}"
        )

    # --- harness_failures.jsonl: malformed lines should log ---

    @pytest.mark.xfail(reason="Regression for issue #6626 — fix not yet landed", strict=False)
    def test_malformed_failure_lines_log_debug(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """Malformed lines in harness_failures.jsonl should log at DEBUG level.

        Currently FAILS because the except Exception at line 226 does ``pass``.
        """
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        outcomes.write_text("")
        scores.write_text("{}")
        failures.write_text(
            '{"category": "hitl_escalation"}\n'
            "CORRUPT LINE\n"
            '{"category": "review_rejection"}\n'
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
            result = compute_trend_metrics(outcomes, scores, failures)

        # total_failures includes all 3 lines (counted before parse)
        assert result.hitl_escalation_rate > 0.0

        # BUG: no debug log about the malformed line
        debug_messages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any(
            "skip" in msg.lower()
            or "malformed" in msg.lower()
            or "corrupt" in msg.lower()
            for msg in debug_messages
        ), (
            f"Expected DEBUG-level log about skipped malformed failure line, "
            f"got: {debug_messages}"
        )

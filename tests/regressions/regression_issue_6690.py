"""Regression test for issue #6690.

RetrospectiveQueue.load catches broad ``Exception`` on corrupt JSONL lines
and logs at ``logger.debug`` level with no ``exc_info=True``.  This means
corrupt queue entries are silently discarded — operators see no warning, no
stack trace, and no indication of which line failed.

The fix requires:
  - Escalating the log from DEBUG to WARNING so operators see corrupt entries.
  - Adding ``exc_info=True`` so the parse-failure stack trace is visible.
  - Narrowing ``except Exception`` to specific parse errors.

This test asserts that corrupt-line log records are emitted at WARNING level
(not DEBUG) and include exc_info.  It is expected to FAIL against the current
code, which uses ``logger.debug(...)`` without ``exc_info=True``.
"""

from __future__ import annotations

import pytest

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retrospective_queue import RetrospectiveQueue  # noqa: E402


def _capture_records(queue: RetrospectiveQueue) -> list[logging.LogRecord]:
    """Load queue while capturing all log records from its logger."""
    target_logger = logging.getLogger("hydraflow.retrospective_queue")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    original_level = target_logger.level
    target_logger.setLevel(logging.DEBUG)
    try:
        queue.load()
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(original_level)
    return records


class TestIssue6690CorruptLineLogLevel:
    """load() must log corrupt queue lines at WARNING, not DEBUG."""

    @pytest.mark.xfail(reason="Regression for issue #6690 — fix not yet landed", strict=False)
    def test_invalid_json_logs_at_warning(self, tmp_path: Path) -> None:
        """A corrupt (non-JSON) line must produce a WARNING log record.

        BUG: Currently emits at DEBUG, so operators never see it unless
        they explicitly enable debug logging for this module.
        """
        queue_file = tmp_path / "retro_queue.jsonl"
        queue_file.write_text("this is not valid json\n")
        queue = RetrospectiveQueue(queue_file)

        records = _capture_records(queue)

        warning_records = [r for r in records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1, (
            "Expected at least 1 WARNING log for a corrupt queue line, "
            f"but got 0.  All records: {[(r.levelno, r.getMessage()) for r in records]}.  "
            "BUG: load() currently logs at DEBUG instead of WARNING (issue #6690)."
        )

    @pytest.mark.xfail(reason="Regression for issue #6690 — fix not yet landed", strict=False)
    def test_pydantic_validation_failure_logs_at_warning(self, tmp_path: Path) -> None:
        """Valid JSON that fails Pydantic validation must also warn.

        BUG: Same root cause — logger.debug on line 72 instead of
        logger.warning.
        """
        queue_file = tmp_path / "retro_queue.jsonl"
        # Valid JSON but missing required 'kind' field
        queue_file.write_text('{"id": "abc123"}\n')
        queue = RetrospectiveQueue(queue_file)

        records = _capture_records(queue)

        warning_records = [r for r in records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1, (
            "Expected at least 1 WARNING log for a Pydantic validation failure, "
            f"but got 0.  All records: {[(r.levelno, r.getMessage()) for r in records]}.  "
            "BUG: load() currently logs at DEBUG instead of WARNING (issue #6690)."
        )

    @pytest.mark.xfail(reason="Regression for issue #6690 — fix not yet landed", strict=False)
    def test_warning_includes_exc_info(self, tmp_path: Path) -> None:
        """The WARNING record must include exc_info for diagnostics.

        BUG: Even if the level were correct, exc_info=True is missing
        from the current logger.debug call.
        """
        queue_file = tmp_path / "retro_queue.jsonl"
        queue_file.write_text("not json at all\n")
        queue = RetrospectiveQueue(queue_file)

        records = _capture_records(queue)

        warning_records = [r for r in records if r.levelno == logging.WARNING]
        if not warning_records:
            # If no WARNING records exist, the level bug must be fixed first.
            # Fall back to checking DEBUG records for exc_info to show both
            # bugs independently.
            debug_records = [r for r in records if r.levelno == logging.DEBUG]
            assert len(debug_records) >= 1, "Expected at least one log record"
            rec = debug_records[0]
            # This will fail because exc_info is None on the current debug call
            assert rec.exc_info is not None and rec.exc_info[1] is not None, (
                "Log record for corrupt queue line must include exc_info=True.  "
                "BUG: logger.debug on line 72 omits exc_info (issue #6690)."
            )
            # Even if exc_info were present, fail because level is wrong
            raise AssertionError(
                "Log level is DEBUG, not WARNING.  Both bugs present (issue #6690)."
            )

        rec = warning_records[0]
        assert rec.exc_info is not None and rec.exc_info[1] is not None, (
            "WARNING log for corrupt queue line must include exc_info=True "
            "so the parse error stack trace is visible.  "
            "BUG: exc_info is missing from the log call (issue #6690)."
        )

"""Regression test for issue #6627.

Bug: ReviewInsightStore.load_recent() and load_proposal_metadata() catch
Exception on malformed records and log a warning, but do NOT include
``exc_info=True``.  This means the Pydantic validation error detail (which
field failed, what the actual value was) is silently dropped from logs.

These tests assert that the warning log records carry ``exc_info`` so that
the full traceback appears in structured logging output.  They will FAIL
(RED) against the current code because ``exc_info=True`` is missing.
"""

from __future__ import annotations

import pytest

import json
import logging
from pathlib import Path

from review_insights import ReviewInsightStore


class TestIssue6627ExcInfoOnMalformedRecords:
    """Warning logs for malformed records must include exc_info."""

    @pytest.mark.xfail(reason="Regression for issue #6627 — fix not yet landed", strict=False)
    def test_load_recent_includes_exc_info_on_malformed_line(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """load_recent() should pass exc_info=True when logging a malformed review.

        Currently FAILS because line 282 omits ``exc_info=True``.
        """
        reviews = tmp_path / "reviews.jsonl"
        # Write a line that is valid JSON but missing required fields so
        # Pydantic validation raises a ValidationError.
        reviews.write_text('{"not_a_valid_field": true}\n')

        store = ReviewInsightStore(tmp_path)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.review_insights"):
            result = store.load_recent(n=10)

        # The malformed line is skipped — empty list returned.
        assert result == []

        # A warning should have been emitted for the malformed line.
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "Expected at least one warning about the malformed record"
        )

        # BUG: exc_info is not set, so the Pydantic ValidationError traceback
        # is lost.  The fix should add ``exc_info=True`` to the logger.warning
        # call so that ``record.exc_info`` is a non-None tuple.
        malformed_warning = warning_records[0]
        assert malformed_warning.exc_info is not None, (
            "logger.warning() was called without exc_info=True — "
            "the Pydantic ValidationError traceback is lost"
        )
        # exc_info should be a (type, value, traceback) tuple
        assert malformed_warning.exc_info[0] is not None, (
            "exc_info tuple has None exception type — "
            "expected the Pydantic ValidationError class"
        )

    @pytest.mark.xfail(reason="Regression for issue #6627 — fix not yet landed", strict=False)
    def test_load_proposal_metadata_includes_exc_info_on_malformed_entry(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """load_proposal_metadata() should pass exc_info=True for malformed entries.

        Currently FAILS because line 313 omits ``exc_info=True``.
        """
        meta_path = tmp_path / "proposal_metadata.json"
        # Write valid JSON structure but with an entry that will fail Pydantic
        # validation (missing required fields like pre_count, proposed_at).
        meta_path.write_text(
            json.dumps(
                {
                    "test_category": {"invalid_field": "bad_value"},
                }
            )
        )

        store = ReviewInsightStore(tmp_path)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.review_insights"):
            result = store.load_proposal_metadata()

        # The malformed entry is skipped — empty dict returned.
        assert result == {}

        # A warning should have been emitted.
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "Expected at least one warning about malformed proposal metadata"
        )

        # BUG: exc_info is not set, so the Pydantic ValidationError traceback
        # is lost.
        malformed_warning = warning_records[0]
        assert malformed_warning.exc_info is not None, (
            "logger.warning() was called without exc_info=True — "
            "the Pydantic ValidationError traceback is lost"
        )
        assert malformed_warning.exc_info[0] is not None, (
            "exc_info tuple has None exception type — "
            "expected the Pydantic ValidationError class"
        )

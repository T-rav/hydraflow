"""Regression test for issue #6419.

Bug: ``verify_proposals`` (src/review_insights.py:636) catches all exceptions
with ``logger.exception("Error during proposal verification")``.
``logger.exception`` logs at ERROR level, which triggers Sentry alerts.

Since ``verify_proposals`` is an analysis/reporting function (not a critical
pipeline step), transient failures should use ``logger.warning(..., exc_info=True)``
instead — preserving the traceback while avoiding false Sentry alerts.

This test forces the exception path and asserts that the resulting log record
is at WARNING level, not ERROR.  It is RED against the current code (which
uses ``logger.exception`` → ERROR level) and GREEN after the fix.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from review_insights import verify_proposals


def test_verify_proposals_exception_logs_warning_not_error(caplog):
    """When verify_proposals hits an unexpected error it must log at WARNING, not ERROR.

    ``logger.exception`` logs at ERROR level → false Sentry alerts.
    After the fix it should use ``logger.warning(..., exc_info=True)``.
    """
    store = MagicMock()
    store.load_proposal_metadata.side_effect = RuntimeError("simulated failure")

    with caplog.at_level(logging.DEBUG, logger="hydraflow.review_insights"):
        result = verify_proposals(store=store, records=[])

    # Function should swallow the error and return empty list
    assert result == []

    # Find the log record for the proposal verification error
    error_records = [
        r
        for r in caplog.records
        if "proposal verification" in r.message.lower()
        or "error during proposal" in r.message.lower()
    ]

    assert error_records, (
        "Expected a log message about proposal verification failure, "
        f"but got: {[r.message for r in caplog.records]}"
    )

    for record in error_records:
        # BUG: current code uses logger.exception → ERROR level.
        # After fix it should be WARNING level.
        assert record.levelno == logging.WARNING, (
            f"verify_proposals logged proposal-verification failure at "
            f"{record.levelname} level (line {record.lineno}), but should use "
            f"WARNING — logger.exception triggers false Sentry alerts. "
            f"See issue #6419."
        )

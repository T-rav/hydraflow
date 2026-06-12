"""Regression for issue #9426 — false "type_annotations" stale review insight.

The review-insight category extractor (`extract_categories`) matched its
keyword list with bare ``substring in summary`` tests. The
``type_annotations`` category keyed off the 3-char keyword ``"type"``, which
is a substring of unrelated infra-telemetry text such as
``API Error: 400 {"type":"error",...}`` and Python's ``TypeError``. Those
API-error / credit-exhaustion summaries were then recorded *as* review
feedback (``ReviewPhase._record_review_insight``), poisoning the per-category
counts so the proposal verifier perpetually re-filed a
``[HITL] Stale review insight: Missing type annotations`` issue.

Two defenses are asserted here:

1. ``extract_categories`` of an API-error-shaped string returns no
   ``type_annotations`` (word-boundary keyword matching, no bare ``"type"``).
2. A ``ReviewResult`` whose ``summary`` starts with an infra-failure marker
   ("API Error", credit exhaustion) is NOT appended as a categorized review
   insight — it is telemetry noise, not a reviewer verdict.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from models import ReviewVerdict
from review_insights import extract_categories

_API_ERROR_SUMMARY = (
    'API Error: 400 {"type":"error","error":'
    '{"type":"invalid_request_error","message":"prompt is too long"}}'
)


def test_api_error_summary_yields_no_type_annotation_category() -> None:
    categories = extract_categories(_API_ERROR_SUMMARY)

    assert "type_annotations" not in categories
    assert categories == []


def test_typeerror_traceback_yields_no_type_annotation_category() -> None:
    summary = "TypeError: 'NoneType' object is not subscriptable"

    assert "type_annotations" not in extract_categories(summary)


def test_real_type_annotation_feedback_still_matches() -> None:
    summary = "Missing type annotation on the new public helper function."

    assert "type_annotations" in extract_categories(summary)


def test_record_review_insight_skips_api_error_summaries(tmp_path: Path) -> None:
    from review_phase._phase import ReviewPhase

    phase = ReviewPhase.__new__(ReviewPhase)
    phase._insights = MagicMock()
    phase._retrospective_queue = None
    phase._config = MagicMock()
    phase._transitioner = MagicMock()
    phase._prs = MagicMock()
    phase._update_bg_worker_status = None

    result = MagicMock()
    result.pr_number = 42
    result.issue_number = 7
    result.verdict = ReviewVerdict.REQUEST_CHANGES
    result.summary = _API_ERROR_SUMMARY
    result.fixes_made = False
    result.transcript = ""

    asyncio.run(phase._record_review_insight(result))

    phase._insights.append_review.assert_not_called()


def test_record_review_insight_records_genuine_feedback(tmp_path: Path) -> None:
    from review_phase._phase import ReviewPhase

    phase = ReviewPhase.__new__(ReviewPhase)
    phase._insights = MagicMock()
    phase._retrospective_queue = None
    phase._config = MagicMock()
    phase._config.review_insight_window = 10
    phase._config.review_pattern_threshold = 3
    phase._config.find_label = ["hydraflow-find"]
    phase._config.hitl_label = ["hydraflow-hitl"]
    phase._transitioner = MagicMock()
    phase._prs = MagicMock()
    phase._update_bg_worker_status = None
    phase._insights.load_recent = MagicMock(return_value=[])
    phase._insights.get_proposed_categories = MagicMock(return_value=set())
    phase._insights.load_proposal_metadata = MagicMock(return_value={})

    result = MagicMock()
    result.pr_number = 42
    result.issue_number = 7
    result.verdict = ReviewVerdict.REQUEST_CHANGES
    result.summary = "Missing type annotations on the new public function."
    result.fixes_made = False
    result.transcript = ""

    asyncio.run(phase._record_review_insight(result))

    phase._insights.append_review.assert_called_once()
    appended = phase._insights.append_review.call_args.args[0]
    assert "type_annotations" in appended.categories

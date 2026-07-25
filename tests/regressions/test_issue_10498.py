"""Regression test for issue #10498 — escape-ledger false-positive bug-issue row.

Detecting commit `9196f7403620` was a docs-only diagram refresh carrying a
``Skip-Regression:`` opt-out trailer, and its ``originating_pr`` was set from
the issue it CLOSED (#10449) rather than the merge that introduced a defect —
neither should ever reach the low-confidence HITL escape surface.
"""

from __future__ import annotations

from escape.detect import detect_escapes
from escape.models import CommitInfo


def test_docs_only_fix_with_skip_regression_trailer_is_not_an_escape() -> None:
    commit = CommitInfo(
        sha="9196f7403620",
        subject=(
            "fix(erosion): refresh JsonlLedger arch diagram for landed "
            "two-tier split"
        ),
        body=(
            "No source or behavior change; only refreshes the architecture "
            "diagram.\n\nSkip-Regression: no code change\n\nCloses #10449."
        ),
        committed_at="2026-07-24T12:01:02-06:00",
    )
    assert detect_escapes([commit]) == []


def test_closing_issue_reference_is_not_recorded_as_originating_pr() -> None:
    commit = CommitInfo(
        sha="deadbeefcafe",
        subject="fix(triage): stop the crash",
        body="Fixes #10449.",
        committed_at="2026-07-24T12:01:02-06:00",
    )
    (candidate,) = detect_escapes([commit])
    assert candidate.originating_pr is None
    assert candidate.originating_ref == "#10449"

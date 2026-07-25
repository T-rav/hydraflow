"""Regression test for issue #10498 — escape-ledger false-positive bug-issue row.

Detecting commit `9196f7403620` was a docs-only diagram refresh carrying a
``Skip-Regression:`` opt-out trailer, and its ``originating_pr`` was set from
the issue it CLOSED (#10449) rather than the merge that introduced a defect —
neither should ever reach the low-confidence HITL escape surface.

Also covers a fallout bug from #10498's append-only resolution mechanism:
``vitals.observe.gather_series_readings`` read the escape ledger with
``read_all()`` instead of the new ``read_latest()`` collapse, so a resolved
escape (recorded as a second row sharing the original's id) was counted
twice in the ``SERIES_ESCAPES`` meta-observability reading (ADR-0046).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from escape.detect import detect_escapes
from escape.ledger import EscapeLedger
from escape.models import CommitInfo, EscapeRecord
from tests.helpers import make_bg_loop_deps
from vitals.models import SERIES_ESCAPES
from vitals.observe import gather_series_readings


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


def test_vitals_escape_reading_not_doubled_by_a_resolution_row(
    tmp_path: Path,
) -> None:
    deps = make_bg_loop_deps(tmp_path)
    config = deps.config
    now = datetime(2026, 7, 25, tzinfo=UTC)

    ledger = EscapeLedger(config.diagnostics_dir / "escape_ledger.jsonl")
    ledger.append(
        EscapeRecord(
            id="bug-issue:9196f74",
            detected_at="2026-07-24T12:01:02+00:00",
            detection_source="bug-issue",
            detection_ref="9196f74",
            originating_pr=None,
            originating_merge_sha="",
            merged_at="",
            time_to_detection_hours=None,
            attribution_method="fixes-chain",
            attribution_confidence="low",
            encoded_as="none-yet",
            notes="",
        )
    )

    before = gather_series_readings(config, now=now, window_days=30)
    assert before[SERIES_ESCAPES] == 1.0

    ledger.append_resolution("bug-issue:9196f74", encoded_as="detector")

    after = gather_series_readings(config, now=now, window_days=30)
    assert after[SERIES_ESCAPES] == 1.0

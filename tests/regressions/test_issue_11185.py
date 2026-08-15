"""Regression: escape-ledger report never rendered the encoding evidence (#11185).

``render_escape_ledger_markdown``'s "Recent escapes" table emitted
``attribution | confidence | encoded_as`` per row but never
``EscapeRecord.notes`` — the only place the concrete encoding (the
regression-test path, ADR number, or stored lesson) is recorded (#10367).
An operator reading ``docs/.../escape-ledger.md`` could see a row was
``encoded_as: regression-test`` but had no way to open the artifact that
closed it without grepping the JSONL.

This pin asserts the issue's intent — that the encoding evidence reaches
the rendered Markdown — and pins *content*, not output shape (gotcha:
regression pins assert content, not output shape; the issue accepts either
a table column or a detail line, so a column-count assertion would
over-pin). The column-count and pipe-escaping/truncation invariants live
in ``tests/test_escape_ledger.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from escape.models import EscapeRecord
from escape.report import render_escape_ledger_markdown


def _record(notes: str, *, encoded_as: str = "regression-test") -> EscapeRecord:
    return EscapeRecord(
        id="revert:deadbeef",
        detected_at="2026-01-20T00:00:00+00:00",
        detection_source="revert",
        detection_ref="deadbeef",
        originating_pr=None,
        originating_merge_sha="abc1234",
        merged_at="2026-01-01T00:00:00+00:00",
        time_to_detection_hours=24.0,
        attribution_method="revert-parse",
        attribution_confidence="high",
        encoded_as=encoded_as,
        notes=notes,
    )


def test_resolved_escape_encoding_notes_render_in_the_report() -> None:
    # #11185: a resolved escape whose notes name the encoding artifact must
    # surface that artifact in the rendered report, not just the JSONL ledger
    # -- an operator reads the Markdown, not the JSONL.
    now = datetime(2026, 2, 1, tzinfo=UTC)
    md = render_escape_ledger_markdown(
        [_record("tests/regressions/test_issue_10367.py")],
        now=now,
        merge_count_30d=200,
    )
    assert "tests/regressions/test_issue_10367.py" in md


def test_evidence_renders_for_a_non_path_encoding_artifact() -> None:
    # The encoding artifact reaches the report regardless of category or
    # shape -- an ADR reference (not a file path) recorded on resolution must
    # also appear, so the evidence column is not silently path-only.
    now = datetime(2026, 2, 1, tzinfo=UTC)
    md = render_escape_ledger_markdown(
        [_record("ADR-0042", encoded_as="adr")],
        now=now,
        merge_count_30d=200,
    )
    assert "ADR-0042" in md

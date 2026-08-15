"""Regression: public escape notes were posted verbatim, unsanitized (#11241).

A sampled re-audit of PR #11197 flagged that
``escape_ledger_loop._resolution_comment`` appended ``record.notes`` to the
PUBLIC GitHub close comment verbatim whenever an ``aging`` surfacing was
answered, and that ``_render_finding`` embedded the same field RAW into a
Markdown table cell in the filed issue body. ``notes`` is unconstrained free
text (a human may pass anything via ``scripts/resolve_escape.py --notes``), so
verbatim publication carried raw newlines into a public comment and a bare ``|``
could break the finding table's column count.

The fix routes every public ``notes`` exit through ``escape.notes``: the close
comment uses ``sanitize_notes_prose`` (collapse whitespace; deliberately no
truncation, so the #11178 evidence path is preserved) and the finding body's
table cell uses ``sanitize_notes_cell`` (collapse + truncate + escape ``|``).
This pin asserts the verbatim leak is closed for both exits WITHOUT suppressing
the evidence.
"""

from __future__ import annotations

from escape.models import EscapeRecord
from escape_ledger_loop import (
    SURFACE_REASON_AGING,
    _render_finding,
    _resolution_comment,
)


def _record(notes: str, *, encoded_as: str = "regression-test") -> EscapeRecord:
    return EscapeRecord(
        id="bug-issue:deadbeef",
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref="deadbeef",
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="high",
        encoded_as=encoded_as,
        notes=notes,
    )


def test_aging_close_comment_collapses_multiline_notes_to_one_line() -> None:
    # #11241: the aging close comment appended record.notes VERBATIM, carrying
    # raw newlines into the public issue. sanitize_notes_prose collapses
    # whitespace so the note is a single safe line, not verbatim text.
    record = _record("line one\nline two\n\nline three")
    comment = _resolution_comment(record, SURFACE_REASON_AGING)
    assert "line one line two line three" in comment
    assert "\nline two" not in comment


def test_aging_close_comment_still_names_the_evidence() -> None:
    # Non-suppression guard: the fix sanitizes, it does NOT drop the evidence.
    # The auto-diagnose reason names a regression-test path past the cell
    # truncation bound; prose must NOT truncate, or #11178's close-comment
    # contract regresses.
    record = _record(
        "auto-diagnose (ADR-0115): regression-pin escape `7fb2ed07e756` is a "
        "real bug, already regression-encoded "
        "(tests/regressions/test_issue_11178.py); recorded at high confidence."
    )
    comment = _resolution_comment(record, SURFACE_REASON_AGING)
    assert "tests/regressions/test_issue_11178.py" in comment


def test_finding_body_table_cell_escapes_a_pipe_in_notes() -> None:
    # #11241: the filed issue body rendered notes RAW in a Markdown table cell;
    # a bare pipe would inject a phantom column. sanitize_notes_cell escapes it.
    record = _record("ADR-0367 | see also #10367")
    _title, body = _render_finding(record, SURFACE_REASON_AGING)
    assert "ADR-0367 \\| see also #10367" in body


def test_finding_body_table_cell_collapses_multiline_notes() -> None:
    # The finding body is a public issue too; raw newlines in the notes cell
    # would break the table row. sanitize_notes_cell collapses them.
    record = _record("line one\nline two")
    _title, body = _render_finding(record, SURFACE_REASON_AGING)
    assert "line one line two" in body

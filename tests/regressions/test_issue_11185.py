"""Regression: escape-ledger report never rendered the encoding evidence (#11185).

``render_escape_ledger_markdown``'s "Recent escapes" table emitted
``attribution | confidence | encoded_as`` per row but never
``EscapeRecord.notes`` — the only place the concrete encoding (the
regression-test path, ADR number, or stored lesson) is recorded (#10367).
An operator reading ``docs/.../escape-ledger.md`` could see a row was
``encoded_as: regression-test`` but had no way to open the artifact that
closed it without grepping the JSONL.

A first attempt at the fix escaped ``|`` BEFORE truncating the cell to
``EVIDENCE_MAX_CHARS``, so a ``|`` sitting near the truncation boundary
could have its escaping backslash kept while the pipe itself was silently
dropped by the slice (or vice versa), corrupting the row's column count.
The fix truncates the raw note text first and escapes second — truncation
can never split an escape sequence that doesn't exist yet.
"""

from __future__ import annotations

from datetime import UTC, datetime

from escape.models import EscapeRecord
from escape.report import EVIDENCE_MAX_CHARS, render_escape_ledger_markdown


def _record(notes: str) -> EscapeRecord:
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
        encoded_as="regression-test",
        notes=notes,
    )


def _table_cells(line: str) -> list[str]:
    """Split a markdown table row into cells, treating ``\\|`` as literal."""
    body = line.strip()
    assert body.startswith("|") and body.endswith("|"), line
    body = body[1:-1]
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            current.append("\\|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def _recent_escapes_row(md: str) -> str:
    lines = md.splitlines()
    idx = lines.index("## Recent escapes")
    return lines[idx + 4]


def test_evidence_column_renders_the_encoding_artifact_path() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    md = render_escape_ledger_markdown(
        [_record("tests/regressions/test_issue_10367.py")],
        now=now,
        merge_count_30d=200,
    )
    row = _recent_escapes_row(md)
    cells = _table_cells(row)
    assert len(cells) == 9, "evidence must be a 9th column, not folded into an existing one"
    assert cells[-1] == "tests/regressions/test_issue_10367.py"


def test_evidence_truncation_never_splits_an_escaped_pipe_at_the_boundary() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    prefix = "tests/regressions/test_issue_11185.py: "
    padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix) - 1)
    # The pipe is the LAST character truncation would keep -- exactly where
    # escape-then-truncate used to corrupt the row.
    notes = f"{prefix}{padding}|" + "b" * 30
    md = render_escape_ledger_markdown([_record(notes)], now=now, merge_count_30d=200)
    row = _recent_escapes_row(md)
    cells = _table_cells(row)
    assert len(cells) == 9, "a pipe at the truncation boundary corrupted the row's cell count"
    evidence = cells[-1]
    assert evidence.startswith(prefix), "leading artifact path must survive truncation"
    assert evidence.endswith("\\|…"), (
        "escaping before truncating leaves a dangling backslash with no "
        f"pipe (got {evidence[-15:]!r}) -- truncate the raw text first"
    )


def test_evidence_truncation_drops_a_pipe_that_falls_past_the_boundary() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    prefix = "tests/regressions/test_issue_11185.py: "
    padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix))
    # The pipe is the FIRST character truncation drops entirely.
    notes = f"{prefix}{padding}|" + "b" * 30
    md = render_escape_ledger_markdown([_record(notes)], now=now, merge_count_30d=200)
    row = _recent_escapes_row(md)
    cells = _table_cells(row)
    assert len(cells) == 9
    evidence = cells[-1]
    assert evidence.startswith(prefix)
    assert evidence.endswith("…")
    assert "|" not in evidence.replace("\\|", ""), "no bare pipe should leak into the cell"

"""Unit tests for escape.notes — safe-Markdown rendering of EscapeRecord.notes (#11241).

``EscapeRecord.notes`` reaches two kinds of PUBLIC GitHub artifact: a Markdown
table cell (the filed HITL issue body and the runtime report) and a prose block
(the close comment). A sampled re-audit of PR #11197 flagged the close comment
for posting ``notes`` verbatim, so every public exit now funnels through one of
two sanitizers in ``escape.notes``. These tests pin both modes independently of
the callers that use them.
"""

from __future__ import annotations

from escape.notes import EVIDENCE_MAX_CHARS, sanitize_notes_cell, sanitize_notes_prose


class TestSanitizeNotesCell:
    """The table-cell mode: collapse + truncate + escape ``|``."""

    def test_empty_returns_em_dash_placeholder(self) -> None:
        assert sanitize_notes_cell("") == "—"

    def test_whitespace_only_returns_em_dash(self) -> None:
        assert sanitize_notes_cell("   \n\t  ") == "—"

    def test_passes_through_simple_evidence(self) -> None:
        assert sanitize_notes_cell("tests/regressions/test_x.py") == (
            "tests/regressions/test_x.py"
        )

    def test_collapses_multiline_to_single_line(self) -> None:
        assert sanitize_notes_cell("line one\nline two\n\nthree") == (
            "line one line two three"
        )

    def test_collapses_runs_of_whitespace(self) -> None:
        assert sanitize_notes_cell("a    b\t\tc") == "a b c"

    def test_escapes_pipe_characters(self) -> None:
        # A bare pipe in a Markdown table cell injects a phantom column.
        assert sanitize_notes_cell("ADR-0367 | see also #10367") == (
            "ADR-0367 \\| see also #10367"
        )

    def test_truncates_at_max_chars_with_ellipsis(self) -> None:
        note = "a" * (EVIDENCE_MAX_CHARS + 20)
        out = sanitize_notes_cell(note)
        assert len(out) == EVIDENCE_MAX_CHARS + 1  # truncated body + ellipsis
        assert out.endswith("…")

    def test_does_not_truncate_at_exactly_the_bound(self) -> None:
        note = "a" * EVIDENCE_MAX_CHARS
        assert sanitize_notes_cell(note) == note

    def test_truncate_then_escape_never_splits_a_pipe_pair(self) -> None:
        # A pipe landing exactly at the truncation boundary must stay intact:
        # escaping BEFORE truncating would leave a dangling backslash with no
        # pipe, corrupting the row's column count.
        prefix = "tests/regressions/test_x.py: "
        padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix) - 1)
        note = f"{prefix}{padding}|" + "b" * 30
        assert sanitize_notes_cell(note).endswith("\\|…")

    def test_truncation_drops_a_pipe_past_the_boundary(self) -> None:
        prefix = "tests/regressions/test_x.py: "
        padding = "a" * (EVIDENCE_MAX_CHARS - len(prefix))
        note = f"{prefix}{padding}|" + "b" * 30
        out = sanitize_notes_cell(note)
        assert out.endswith("…")
        assert "|" not in out.replace("\\|", "")


class TestSanitizeNotesProse:
    """The prose mode: collapse whitespace only.

    Prose does NOT truncate: the close comment's whole purpose (#11178) is to
    name the encoding evidence, and the auto-diagnose reason string places the
    regression-test path past the cell truncation bound — truncating here would
    silently drop the evidence the comment exists to surface. The
    information-disclosure concern raised in #11241 is mitigated by the operator
    contract (the CLI ``--notes`` help names the public destination), not by
    truncation. A literal ``|`` in a paragraph is harmless Markdown, so it is
    left unescaped (escaping would render a stray backslash).
    """

    def test_empty_returns_empty_string(self) -> None:
        # So the caller's `if sanitized:` guard omits the clause entirely.
        assert sanitize_notes_prose("") == ""

    def test_whitespace_only_returns_empty_string(self) -> None:
        assert sanitize_notes_prose("   \n\t  ") == ""

    def test_passes_through_simple_evidence(self) -> None:
        assert sanitize_notes_prose("tests/regressions/test_x.py") == (
            "tests/regressions/test_x.py"
        )

    def test_collapses_multiline_to_single_line(self) -> None:
        # Verbatim publication would carry raw newlines into the public comment.
        assert sanitize_notes_prose("line one\nline two\n\nthree") == (
            "line one line two three"
        )

    def test_collapses_runs_of_whitespace(self) -> None:
        assert sanitize_notes_prose("a    b\t\tc") == "a b c"

    def test_does_not_escape_pipe_characters(self) -> None:
        # A literal pipe in a prose paragraph is harmless; escaping would render
        # a visible stray backslash (#11241).
        assert sanitize_notes_prose("ADR-0367 | see also #10367") == (
            "ADR-0367 | see also #10367"
        )

    def test_does_not_truncate_long_evidence(self) -> None:
        # The auto-diagnose reason is ~180 chars and names the encoding path past
        # char 100; truncation would drop it (#11178). Prose stays unbounded.
        note = (
            "auto-diagnose (ADR-0115): regression-pin escape `7fb2ed07e756` "
            "is a real bug, already regression-encoded "
            "(tests/regressions/test_issue_11178.py); recorded at high confidence."
        )
        out = sanitize_notes_prose(note)
        assert out == " ".join(note.split())
        assert "tests/regressions/test_issue_11178.py" in out
        assert "…" not in out

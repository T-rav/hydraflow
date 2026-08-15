"""Safe-Markdown rendering of ``EscapeRecord.notes`` for public artifacts (#11241).

``notes`` is free text accepted from two sources — the machine auto-diagnoser
(``escape.auto_diagnose``, ADR-0115, evidence-only strings) and a human operator
(``scripts/resolve_escape.py --notes "..."``, unconstrained). Both feed the same
append-only ledger row, and that row's ``notes`` reaches PUBLIC GitHub
artifacts: the filed HITL issue body (a Markdown table cell, via
``escape_ledger_loop._render_finding``) and the close comment (prose, via
``_resolution_comment``). A sampled re-audit of PR #11197 (#11241) flagged the
close comment for posting ``notes`` verbatim — untransformed, with raw
newlines — so every public exit now funnels through one of these two sanitizers.

Two modes, differing only in pipe handling and truncation:

* :func:`sanitize_notes_cell` — for a Markdown TABLE cell (the finding body and
  the runtime report): collapses whitespace, truncates at
  ``EVIDENCE_MAX_CHARS``, and escapes ``|`` → ``\\|`` so a pipe cannot inject a
  phantom column. Truncation happens on the collapsed raw text BEFORE escaping,
  so no ``\\|`` pair is ever split at the length boundary.
* :func:`sanitize_notes_prose` — for a prose block (the close comment):
  collapses whitespace, but does NOT truncate and does NOT escape ``|``. A
  literal pipe in a paragraph is harmless Markdown (escaping would render a
  visible stray backslash), and the close comment's whole purpose (#11178) is to
  NAME the encoding evidence — the auto-diagnose reason string places the
  regression-test path past the cell truncation bound, so truncating here would
  silently drop the very evidence the comment exists to surface.

Sanitizing shapes the text into safe, single-line Markdown; it is NOT a
disclosure filter. The information-disclosure concern raised in #11241 is
mitigated by the operator contract — the CLI ``--notes`` help and the filed
issue's remediation block name the public destination so a human keeps
``--notes`` evidence-only.
"""

from __future__ import annotations

#: Maximum characters of ``notes`` rendered into a Markdown TABLE cell. The
#: runtime report's "Recent escapes" table and the filed HITL issue body both
#: render notes as one cell, so a bound keeps the row readable. Prose
#: (:func:`sanitize_notes_prose`) is intentionally unbounded — see module doc.
EVIDENCE_MAX_CHARS = 100


def _collapse(notes: str) -> str:
    """Collapse every run of whitespace (newlines/tabs/spaces) to a single space."""
    return " ".join(notes.split())


def _truncate(text: str) -> str:
    """Bound *text* at ``EVIDENCE_MAX_CHARS``, appending an ellipsis if cut.

    Operates on already-collapsed text so there is no ``\\|`` escape sequence
    yet to slice in half at the boundary.
    """
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "…"
    return text


def sanitize_notes_cell(notes: str) -> str:
    """Render ``notes`` as a single safe Markdown table cell.

    Collapses whitespace, truncates at ``EVIDENCE_MAX_CHARS``, then escapes
    ``|`` → ``\\|`` (in that order, so truncation cannot split an escape pair).
    Returns ``"—"`` for empty/whitespace-only input — the table's placeholder
    for a row with no recorded evidence.
    """
    prepared = _truncate(_collapse(notes))
    if not prepared:
        return "—"
    return prepared.replace("|", "\\|")


def sanitize_notes_prose(notes: str) -> str:
    """Render ``notes`` for a prose block (e.g. a GitHub close comment).

    Collapses whitespace (so raw newlines never reach the public comment) but
    does NOT truncate and does NOT escape ``|`` — see the module docstring for
    why both are deliberately omitted. Returns ``""`` for empty/whitespace-only
    input so the caller's ``if sanitized:`` guard omits the notes clause rather
    than appending an empty fragment.
    """
    return _collapse(notes)

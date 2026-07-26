"""Regression for issue #10591.

``_STYLE_A_RE`` in ``wiki_rot_citations`` was ``\\b([\\w./-]+\\.py):(\\w+)``.
Because ``\\w+`` matches digits, ordinary *line references* like
``base_background_loop.py:141`` were extracted as Style-A ("colon") cites
with symbol ``"141"``. Such a symbol can never resolve via
``verify_cite_ast``, so ``WikiRotDetectorLoop`` reported them broken forever
and escalated them after 3 attempts — a permanent false-positive class.

The fix: ``extract_cites`` must treat a purely-numeric tail as a line
reference and NOT emit it as a symbol cite, while a real ``path.py:Symbol``
tail (including dotted ``Bar.baz``) is still emitted.
"""

from __future__ import annotations

from wiki_rot_citations import extract_cites


def test_extract_cites_skips_numeric_line_reference() -> None:
    # A ``.py:NNN`` line reference must NOT surface as a symbol cite.
    text = "See base_background_loop.py:141 for the base class."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("base_background_loop.py", "141", "colon") not in got
    # No colon-style cite should be produced at all for a pure line ref.
    assert all(c.style != "colon" for c in extract_cites(text))


def test_extract_cites_skips_multiple_numeric_line_references() -> None:
    text = "orchestrator.py:948 and phase_utils.py:392 are line refs."
    symbols = {c.symbol for c in extract_cites(text) if c.style == "colon"}
    assert "948" not in symbols
    assert "392" not in symbols


def test_extract_cites_still_yields_symbol_cite() -> None:
    # A genuine ``path.py:Symbol`` tail must still be extracted.
    text = "The guard lives in src/foo.py:Bar.baz today."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    # Regex captures the leading identifier segment of the dotted symbol.
    assert ("src/foo.py", "Bar", "colon") in got


def test_extract_cites_mixed_line_ref_and_symbol() -> None:
    text = "src/foo.py:bar defined near helper.py:57."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("src/foo.py", "bar", "colon") in got
    assert ("helper.py", "57", "colon") not in got

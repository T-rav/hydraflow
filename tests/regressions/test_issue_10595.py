"""Regression for issue #10595.

The wiki entry that documents the rot detector itself
(``docs/wiki/terms/wiki-rot-detector-loop.md``) explains the cite grammar
with the literal format examples ``path.py:symbol`` (Style-A) and
``src.module.Class`` (Style-B). ``extract_cites`` extracted both as real
cites, and neither can ever resolve, so ``WikiRotDetectorLoop`` reported its
own documentation as rotten forever and escalated it after 3 attempts — a
permanent self-referential false-positive class.

The fix: ``extract_cites`` recognizes a *documentation placeholder* cite —
a metavariable symbol (``symbol`` / ``some_symbol`` / ``Class`` / ``module``)
paired with an illustrative placeholder module (``path.py`` / ``src.module`` /
``path/to/file.py`` …) — and does NOT emit it. A genuine ``module.py:Symbol``
cite (real-looking module, even if the symbol is missing) is still emitted so
real wiki rot is still reported.
"""

from __future__ import annotations

from wiki_rot_citations import extract_cites


def _pairs(text: str) -> set[tuple[str, str]]:
    return {(c.module, c.symbol) for c in extract_cites(text)}


def test_style_a_placeholder_cite_is_not_extracted() -> None:
    # The exact Style-A format example from the wiki entry.
    text = "extracts code references via three patterns (`path.py:symbol`, ...)"
    assert ("path.py", "symbol") not in _pairs(text)


def test_style_b_placeholder_cite_is_not_extracted() -> None:
    # The exact Style-B format example from the wiki entry.
    text = "dotted `src.module.Class`, and bare identifiers inside fenced blocks"
    assert ("src.module", "Class") not in _pairs(text)


def test_illustrative_path_to_file_placeholder_is_not_extracted() -> None:
    text = "an illustrative `path/to/file.py:some_symbol` in prose"
    assert ("path/to/file.py", "some_symbol") not in _pairs(text)


def test_documentation_line_yields_no_hard_cites() -> None:
    # The verbatim line 19 of docs/wiki/terms/wiki-rot-detector-loop.md.
    text = (
        "On each tick it walks every `RepoWikiStore`-registered repo's wiki "
        "entries, extracts code references via three patterns "
        "(`path.py:symbol`, dotted `src.module.Class`, and bare identifiers "
        "inside fenced code blocks as hints only), then verifies each hard cite."
    )
    assert _pairs(text) == set()


def test_genuine_broken_cite_still_reported() -> None:
    # A real-looking module with a missing symbol must STILL be extracted so
    # genuine wiki rot keeps being reported — the fix must not over-suppress.
    text = "The guard lives in wiki_rot_citations.py:missing_helper today."
    assert ("wiki_rot_citations.py", "missing_helper") in _pairs(text)


def test_metavar_symbol_on_real_module_is_not_suppressed() -> None:
    # A metavariable-shaped symbol on a REAL module path is not a placeholder:
    # only the (placeholder-module AND metavariable-symbol) combination is.
    text = "See real_loop.py:Class for the base."
    assert ("real_loop.py", "Class") in _pairs(text)


def test_real_symbol_on_placeholder_module_is_not_suppressed() -> None:
    # A real symbol on a placeholder module still surfaces (only the
    # metavariable pairing is a documentation example).
    text = "look at path.py:handle_request for details"
    assert ("path.py", "handle_request") in _pairs(text)

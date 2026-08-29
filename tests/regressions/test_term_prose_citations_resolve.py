"""Regression: term-file PROSE cited a class that no longer existed (#11762).

After the Council -> panel rename, ``ADRCouncilReviewer`` was gone from
``src/`` entirely, yet two term files still documented the loop as
delegating to it:

- ``docs/wiki/terms/adr-reviewer-loop.md``  (Definition *and* Invariants)
- ``docs/wiki/terms/adr-pre-validator.md``  (Definition)

The ADR-0053 drift gate stayed green throughout, because it checks that a
term's ``code_anchor`` frontmatter field resolves -- and both anchors
pointed at ``ADRReviewerLoop``, which still existed. An anchor check on one
symbol says nothing about a different symbol cited in the prose body.

This matters more than a stale doc: term files are rendered into
``docs/arch/generated/ubiquitous-language.md``, so the retired sense
propagated into the canonical glossary that ADR-0053 exists to keep
single-valued.

Pins: every backticked CamelCase citation in a term file's body resolves
to either a symbol defined in ``src/`` or the name of a declared term.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
TERMS = REPO_ROOT / "docs" / "wiki" / "terms"

# A backticked dotted identifier, captured WHOLE. The first draft captured
# only the head and treated ``.Tail`` as a strippable method suffix, so a
# citation like ``adr_reviewer_loop.ADRCouncilReviewer`` was checked as the
# lowercase module name alone -- which ``_is_class_like`` then skipped, so
# NEITHER half was ever verified. Six dotted citations live in the corpus.
_CITATION = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_]\w*)*)(?:\(\))?`")


def _cited_symbols(text: str) -> set[str]:
    """Every class-like segment of every backticked citation.

    Dotted citations contribute each of their segments independently, so
    ``module.Class`` is checked on ``Class`` rather than on ``module``.
    """
    found: set[str] = set()
    for token in _CITATION.findall(text):
        for segment in token.split("."):
            if _is_class_like(segment):
                found.add(segment)
    return found


def _is_class_like(name: str) -> bool:
    """Two or more capitals AND at least one lowercase.

    Deliberately NOT "capital, then a lowercase run" -- that pattern cannot
    match a LEADING ACRONYM, so it silently skips ``ADRCouncilReviewer``,
    ``ADRReviewPanel``, ``HTTPClient``. The first draft of this guard used
    it and passed the very mutation it was written to catch. The two-capital
    rule keeps ALL-CAPS prose words (``OK``, ``SIGKILL``, ``README``) and
    ordinary capitalised words (``Proposed``) out, without that blind spot.
    """
    return sum(1 for c in name if c.isupper()) >= 2 and any(
        c.islower() for c in name
    )

_NAME_FIELD = re.compile(r'^name:\s*"?([^"\n]+)"?\s*$', re.MULTILINE)

# Names that are legitimately neither a src/ symbol nor a declared term.
# Deliberately EMPTY: the residual list sits on the side where a miss is
# LOUD. If a real citation lands here, this test goes red and a maintainer
# either fixes the prose or adds the name WITH a reason -- rather than a
# stale citation slipping through in silence, which is the defect above.
_ALLOWED_UNRESOLVED: dict[str, str] = {}


def _symbols_defined_in_src() -> set[str]:
    names: set[str] = set()
    for py in SRC.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                names.add(node.name)
    return names


def _declared_term_names() -> set[str]:
    names: set[str] = set()
    for md in TERMS.glob("*.md"):
        match = _NAME_FIELD.search(md.read_text(encoding="utf-8"))
        if match:
            names.add(match.group(1).strip())
    return names


def _body_of(md: Path) -> str:
    """Prose only -- the frontmatter block is machine-checked elsewhere."""
    parts = md.read_text(encoding="utf-8").split("---", 2)
    return parts[2] if len(parts) >= 3 else parts[0]


def test_the_guard_is_looking_at_real_files() -> None:
    """Anti-vacuity: a scan over an empty corpus would pass silently."""
    term_files = list(TERMS.glob("*.md"))
    assert len(term_files) > 50, f"expected the term corpus, found {len(term_files)}"
    assert len(_symbols_defined_in_src()) > 500, "src/ symbol scan came back tiny"
    cited = sum(len(_cited_symbols(_body_of(md))) for md in term_files)
    assert cited > 20, f"only {cited} prose citations found; the regex stopped matching"


def test_every_prose_citation_in_a_term_file_resolves() -> None:
    resolvable = _symbols_defined_in_src() | _declared_term_names()
    unresolved: dict[str, list[str]] = {}
    for md in sorted(TERMS.glob("*.md")):
        for symbol in sorted(_cited_symbols(_body_of(md))):
            if symbol in resolvable or symbol in _ALLOWED_UNRESOLVED:
                continue
            unresolved.setdefault(symbol, []).append(md.name)

    assert not unresolved, (
        "term-file prose cites symbols that exist neither in src/ nor as a "
        "declared term -- the #11762 signature (a rename that updated the "
        "code and the anchor but not the prose):\n"
        + "\n".join(f"  {sym}: {', '.join(files)}" for sym, files in unresolved.items())
    )


def test_the_predicate_matches_leading_acronym_class_names() -> None:
    """The blind spot that made this guard's own first draft vacuous.

    ``ADRCouncilReviewer`` -- the symbol the regression is about -- begins
    with an acronym. A predicate anchored on "capital then lowercase" skips
    it entirely and the guard passes while blind.
    """
    for name in ("ADRCouncilReviewer", "ADRReviewPanel", "HTTPClient", "IOError"):
        assert _is_class_like(name), f"{name} must be treated as a citation"
    for name in ("OK", "SIGKILL", "README", "Proposed", "HOUSEKEEPING"):
        assert not _is_class_like(name), f"{name} must not be treated as a citation"


def test_the_regex_sees_both_halves_of_a_dotted_citation() -> None:
    """The blind spot that let a dotted citation through entirely.

    ``adr_reviewer_loop.ADRCouncilReviewer`` was captured as the module name
    alone, which ``_is_class_like`` skips -- so the class half was never
    checked and the module half never either. Six dotted citations are live
    in the corpus today.
    """
    assert _cited_symbols("`adr_reviewer_loop.ADRCouncilReviewer`") == {
        "ADRCouncilReviewer"
    }
    assert _cited_symbols("`base_runner.BaseRunner`") == {"BaseRunner"}
    assert _cited_symbols("`ADRReviewPanel.review_proposed_adrs()`") == {
        "ADRReviewPanel"
    }
    # A lone lowercase module name is not a class citation and must not be
    # reported as an unresolved symbol.
    assert _cited_symbols("`config.adr_review_interval`") == set()

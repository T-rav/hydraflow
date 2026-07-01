"""Read-only UL glossary drift check (ADR-0053, ADR-0098 Task 15).

`make lint-ul` is the source-generating command, but it MUTATES the repo (it
writes `docs/arch/generated/ubiquitous-language.md`), which disqualifies it
from being an `enforced` ADR-0098 check — mutating checks aren't allowed to
gate the coverage ratchet (`adr_conformance.is_mutating`).

This test performs the same render `scripts/lint_ubiquitous_language.py`
does — load terms from `docs/wiki/terms/` via `TermStore`, render with
`render_glossary` — entirely in memory, and asserts the result is byte-equal
to the committed `docs/arch/generated/ubiquitous-language.md`. It never
writes anything, so it safely gates CI without silently "fixing" drift.

If this test fails, the glossary is stale: run `make lint-ul` and commit the
regenerated file (or fix the term files that caused the diff).
"""

from __future__ import annotations

from pathlib import Path

from ubiquitous_language import TermStore, render_glossary

REPO = Path(__file__).resolve().parent.parent
TERMS_DIR = REPO / "docs" / "wiki" / "terms"
GLOSSARY_PATH = REPO / "docs" / "arch" / "generated" / "ubiquitous-language.md"


def test_committed_glossary_matches_rendered_terms() -> None:
    """`docs/arch/generated/ubiquitous-language.md` must equal
    `render_glossary(TermStore(docs/wiki/terms).list())` — the same
    computation `make lint-ul` performs, checked read-only so it can be an
    `enforced` ADR-0053 gate without mutating the working tree.
    """
    terms = TermStore(TERMS_DIR).list()
    rendered = render_glossary(terms)
    committed = GLOSSARY_PATH.read_text()

    assert rendered == committed, (
        "docs/arch/generated/ubiquitous-language.md is out of sync with "
        "docs/wiki/terms/. Run `make lint-ul` and commit the regenerated "
        "glossary."
    )

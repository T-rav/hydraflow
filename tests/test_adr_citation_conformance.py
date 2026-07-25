# tests/test_adr_citation_conformance.py
"""Violation-based ADR citation conformance gate (#10540, #10533).

Replaces the activity-based ADR-drift heuristic (AdrTouchpointAuditorLoop →
AdrDriftResolverLoop, ~70% false positives) with a deterministic guard: every
symbol-qualified `src/...py:Symbol` citation in an ADR MUST resolve against the
current source tree via ``ast.parse``. A citation whose file is missing, or
whose symbol no longer resolves, is a *violation* — a concrete, actionable
fact, not a probabilistic "a cited module changed in a PR" signal.

The repo-wide test (``test_no_unresolved_adr_citations``) runs in the normal
"Tests" CI lane, so any future PR that renames or deletes a cited symbol fails
CI with the exact citation to fix.
"""

from __future__ import annotations

from pathlib import Path

from adr_citation_resolve import unresolved_citations
from adr_index import ADRIndex

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"


# ---------------------------------------------------------------------------
# Repo-wide CI gate
# ---------------------------------------------------------------------------


def test_no_unresolved_adr_citations() -> None:
    """Every symbol-qualified ADR citation resolves against the live source tree.

    Deterministic replacement for activity-based ADR-drift detection: this
    fails the "Tests" lane the moment a PR renames/deletes a symbol an ADR
    still cites, naming the exact citation to fix.
    """
    unresolved = unresolved_citations(ADRIndex(ADR_DIR))
    rendered = "\n".join(
        f"  ADR-{number:04d}  {path}:{symbol}"
        if symbol
        else f"  ADR-{number:04d}  {path}"
        for number, path, symbol in unresolved
    )
    assert not unresolved, (
        "ADR citations that no longer resolve against the source tree "
        f"({len(unresolved)}):\n{rendered}\n\n"
        "Fix the ADR citation: correct the renamed symbol, drop the ':Symbol' "
        "qualifier if the file is still cited but the symbol moved, or remove "
        "the citation if the file is gone."
    )


# ---------------------------------------------------------------------------
# Focused unit tests (tmp_path fixtures)
# ---------------------------------------------------------------------------


def _write_adr(adr_dir: Path, number: int, *citations: str) -> None:
    """Write a minimal Accepted ADR that cites each of *citations* in backticks."""
    cited = " ".join(f"`{c}`" for c in citations)
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / f"{number:04d}-fixture.md").write_text(
        f"# ADR-{number:04d}: Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-07-25\n\n"
        "## Context\n\n"
        f"Fixture ADR citing {cited}.\n"
    )


def _index(tmp_path: Path) -> ADRIndex:
    return ADRIndex(tmp_path / "docs" / "adr")


def test_bare_symbol_resolves(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class Bar:\n    pass\n")
    _write_adr(tmp_path / "docs" / "adr", 1, "src/foo.py:Bar")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_module_level_constant_resolves(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("MAX_RETRIES = 3\n")
    _write_adr(tmp_path / "docs" / "adr", 1, "src/foo.py:MAX_RETRIES")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_dotted_method_resolves(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text(
        "class Bar:\n    def baz(self):\n        pass\n"
    )
    _write_adr(tmp_path / "docs" / "adr", 1, "src/foo.py:Bar.baz")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_dead_symbol_does_not_resolve(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class Bar:\n    pass\n")
    _write_adr(tmp_path / "docs" / "adr", 7, "src/foo.py:Ghost")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == [
        (7, "src/foo.py", "Ghost")
    ]


def test_dead_dotted_method_does_not_resolve(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text(
        "class Bar:\n    def baz(self):\n        pass\n"
    )
    _write_adr(tmp_path / "docs" / "adr", 7, "src/foo.py:Bar.gone")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == [
        (7, "src/foo.py", "Bar.gone")
    ]


def test_dead_path_does_not_resolve(tmp_path: Path) -> None:
    _write_adr(tmp_path / "docs" / "adr", 7, "src/missing.py:Bar")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == [
        (7, "src/missing.py", "Bar")
    ]


def test_bare_file_citation_present_file_resolves(tmp_path: Path) -> None:
    """A bare `src/foo.py` citation (no :Symbol) resolves when the file exists."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("x = 1\n")
    _write_adr(tmp_path / "docs" / "adr", 1, "src/foo.py")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_bare_file_citation_missing_file_is_exempt(tmp_path: Path) -> None:
    """A BARE `src/foo.py` citation to a missing file is NOT a violation.

    Bare citations are file-level dependency pointers, not decision anchors:
    a removal ADR legitimately cites a deleted file (ADR-0065 removes and
    cites ``src/code_grooming_loop.py``), and a Proposed ADR forward-references
    a planned file (ADR-0087's ``src/prompt_template.py``). Only
    symbol-qualified citations are enforced.
    """
    _write_adr(tmp_path / "docs" / "adr", 9, "src/missing.py")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_glob_pattern_path_is_exempt(tmp_path: Path) -> None:
    """A glob/placeholder path (``src/*_loop.py``) is illustrative, not a file."""
    _write_adr(tmp_path / "docs" / "adr", 9, "src/*_loop.py")

    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []


def test_superseded_adr_citations_are_not_checked(tmp_path: Path) -> None:
    """Superseded ADRs are frozen history — their dead citations are exempt."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0009-old.md").write_text(
        "# ADR-0009: Old\n\n"
        "**Status:** Superseded by ADR-0010\n\n"
        "## Context\n\n"
        "Cites `src/missing.py:Ghost`.\n"
    )
    assert unresolved_citations(_index(tmp_path), repo_root=tmp_path) == []

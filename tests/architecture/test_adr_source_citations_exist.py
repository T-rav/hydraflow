"""Ratchet: every live ADR's ``src/...py`` citation must resolve to a real file.

Issue #9649 (umbrella; subsumes #9514, #9824, #9497, #9920, #9921). ADRs cite
source files as ``` `src/foo.py` ``` or ``` `src/foo.py:Symbol` ```. When a
module is renamed, split into a package, or deleted, those citations rot: the
P2 drift gate (``adr_index.adrs_touching``) can never fire for the cited path
because nothing at that path is ever touched, so the ADR silently loses its
drift coverage (the #9514 double-colon typo was the same failure mode — an
unparseable citation is a dead one).

This test extracts citations with the SAME regex the runtime uses
(``adr_index._SOURCE_FILE_CITATION_RE``) so the test's notion of "a citation"
is exactly the drift gate's, then asserts each cited path exists. It is a
one-way ratchet: no NEW dead citation can be added to a live (Accepted /
Proposed) ADR, and the two documented exceptions below stay explicit.

Scope decisions:
  * Only Accepted / Proposed ADRs are checked — Superseded / Deprecated ADRs
    never fire the drift gate, so a dead citation there is harmless history.
  * Glob / placeholder citations (``src/**/*.py``, ``src/*_loop.py``,
    ``src/<domain>/*.py``) are skipped — they are patterns, not file paths.
  * ``_PERMANENT_ALLOWLIST`` holds paths that are *intentionally* absent and
    documented as such by their citing ADR. It is guarded (see
    ``test_permanent_allowlist_entries_are_actually_missing``) so it cannot
    silently accrue stale entries.
  * ``_GRANDFATHER`` holds not-yet-repointed dead paths so the ratchet can be
    landed green and burned down later. It is empty today (everything
    resolvable was repointed in #9649) and may only SHRINK.
"""

from __future__ import annotations

from pathlib import Path

from adr_index import scan_adr_directory

# Paths deliberately absent from the tree, documented by their citing ADR.
_PERMANENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # ADR-0065 (Accepted) documents the intentional REMOVAL of this loop.
        "src/code_grooming_loop.py",
        # ADR-0087 (Proposed) is aspirational; prompt_template.py is future
        # work that was never built. Repoint or drop when the ADR is decided.
        "src/prompt_template.py",
    }
)

# Not-yet-repointed dead citations. May only SHRINK. Empty by design.
_GRANDFATHER: frozenset[str] = frozenset()

_LIVE_STATUSES = frozenset({"Accepted", "Proposed"})


def _is_glob(path: str) -> bool:
    """True for pattern citations (globs / ``<placeholder>`` templates)."""
    return any(ch in path for ch in "*<>?[")


def _cited_paths_by_adr(adr_dir: Path) -> list[tuple[int, str]]:
    """(adr_number, cited_path) for every non-glob citation in a live ADR.

    Uses the same directory scan + citation regex the runtime drift gate uses.
    """
    pairs: list[tuple[int, str]] = []
    for adr in scan_adr_directory(adr_dir):
        if adr.status not in _LIVE_STATUSES:
            continue
        for path in sorted(adr.source_files):
            if _is_glob(path):
                continue
            pairs.append((adr.number, path))
    return pairs


def test_live_adr_source_citations_resolve(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    dead: list[str] = []
    for number, path in _cited_paths_by_adr(adr_dir):
        if path in _PERMANENT_ALLOWLIST or path in _GRANDFATHER:
            continue
        if not (real_repo_root / path).exists():
            dead.append(f"ADR-{number:04d}: `{path}` does not exist")

    assert dead == [], (
        "Live ADRs cite source paths that no longer exist. Repoint each "
        "citation to the file/symbol's real home, or (if the code was "
        "intentionally removed) mark the ADR Superseded / reword the citation "
        "to plain prose. Dead citations silently disable the P2 drift gate for "
        "that ADR.\n  " + "\n  ".join(dead)
    )


def test_grandfather_entries_still_dead(real_repo_root: Path) -> None:
    """The grandfather list may only shrink: an entry that now resolves must
    be removed (and its citation is already correct)."""
    resurfaced = [path for path in _GRANDFATHER if (real_repo_root / path).exists()]
    assert resurfaced == [], (
        "These grandfathered paths now exist — remove them from _GRANDFATHER:\n  "
        + "\n  ".join(sorted(resurfaced))
    )


def test_permanent_allowlist_entries_are_actually_missing(
    real_repo_root: Path,
) -> None:
    """Guard the permanent allowlist against rot: each entry must be a path
    that is genuinely absent (removed or never-built code). If one reappears,
    the allowlist entry is stale — repoint the citation and drop it here."""
    present = [
        path for path in _PERMANENT_ALLOWLIST if (real_repo_root / path).exists()
    ]
    assert present == [], (
        "These permanent-allowlist paths now exist in the tree — the code was "
        "(re)introduced, so the citation should be repointed and the entry "
        "removed from _PERMANENT_ALLOWLIST:\n  " + "\n  ".join(sorted(present))
    )


def test_permanent_allowlist_entries_are_cited_by_a_live_adr(
    real_repo_root: Path,
) -> None:
    """Guard against dead allowlist entries: every permanent exception must
    still be cited by some live ADR, otherwise it is dead config to delete."""
    adr_dir = real_repo_root / "docs" / "adr"
    cited = {path for _number, path in _cited_paths_by_adr(adr_dir)}
    orphaned = sorted(_PERMANENT_ALLOWLIST - cited)
    assert orphaned == [], (
        "These permanent-allowlist paths are no longer cited by any live ADR — "
        "delete them from _PERMANENT_ALLOWLIST:\n  " + "\n  ".join(orphaned)
    )

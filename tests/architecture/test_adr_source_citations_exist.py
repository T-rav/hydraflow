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

Issue #10440 closed a gap in the ratchet above: it only ever iterated
*parsed* citations (``adr.source_files``), so a citation that fails to
parse at all — a doubled ``::``, a trailing ``()`` — was invisible to it.
``test_no_unparseable_source_citations`` below extracts every backtick
`` `src/...py...` `` -shaped token from a live ADR's raw text with a
deliberately looser regex, then asserts each one fullmatches
``adr_index._SOURCE_FILE_CITATION_RE`` (the strict runtime regex). A token
that fails is dead on arrival: it never reaches ``source_files``, so the
drift gate silently never fires for it. ``_UNPARSEABLE_GRANDFATHER`` mirrors
``_GRANDFATHER`` above (empty by design; may only shrink).
"""

from __future__ import annotations

import re
from pathlib import Path

from adr_index import _SOURCE_FILE_CITATION_RE, scan_adr_directory

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

# Deliberately looser than adr_index._SOURCE_FILE_CITATION_RE: matches ANY
# backtick-wrapped span that starts with `src/` and contains `.py`, so it
# also catches malformed citations (a doubled `::`, a trailing `()`) that
# the strict regex silently refuses to match at all.
_LENIENT_SRC_TOKEN_RE = re.compile(r"`(src/[^`]*\.py[^`]*)`")

# Not-yet-repointed unparseable tokens. May only SHRINK. Empty by design
# (#10440 repointed every token found when this ratchet was introduced).
_UNPARSEABLE_GRANDFATHER: frozenset[str] = frozenset()


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


def _adr_number_from_filename(name: str) -> int | None:
    match = re.match(r"(\d{4})-", name)
    return int(match.group(1)) if match else None


def _unparseable_tokens_by_adr(adr_dir: Path) -> list[tuple[int, str]]:
    """(adr_number, raw_token) for every lenient `src/...py...` token in a
    live ADR's raw text that does NOT fullmatch the strict citation regex."""
    statuses = {adr.number: adr.status for adr in scan_adr_directory(adr_dir)}
    pairs: list[tuple[int, str]] = []
    for path in sorted(adr_dir.glob("*.md")):
        number = _adr_number_from_filename(path.name)
        if number is None or statuses.get(number) not in _LIVE_STATUSES:
            continue
        text = path.read_text()
        for token in _LENIENT_SRC_TOKEN_RE.findall(text):
            if _is_glob(token):
                continue
            if _SOURCE_FILE_CITATION_RE.fullmatch(f"`{token}`"):
                continue
            pairs.append((number, token))
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


def test_no_unparseable_source_citations(real_repo_root: Path) -> None:
    """No live ADR may contain a `src/...py`-shaped citation token that fails
    to fullmatch the strict runtime regex (#10440)."""
    adr_dir = real_repo_root / "docs" / "adr"
    unparseable = [
        (number, token)
        for number, token in _unparseable_tokens_by_adr(adr_dir)
        if token not in _UNPARSEABLE_GRANDFATHER
    ]
    assert unparseable == [], (
        "Live ADRs contain backtick `src/...py` tokens that fail to parse as "
        "source-file citations (e.g. a doubled `::` or a trailing `()`). An "
        "unparseable citation silently drops out of source_files, so the P2 "
        "drift gate can never fire for it. Fix the citation syntax (a single "
        "`:Symbol` tail, no trailing parens).\n  "
        + "\n  ".join(f"ADR-{n:04d}: `{t}`" for n, t in unparseable)
    )


def test_unparseable_grandfather_entries_still_unparseable(
    real_repo_root: Path,
) -> None:
    """The grandfather list may only shrink: an entry that now parses cleanly
    must be removed."""
    adr_dir = real_repo_root / "docs" / "adr"
    still_bad = {token for _number, token in _unparseable_tokens_by_adr(adr_dir)}
    resolved = sorted(_UNPARSEABLE_GRANDFATHER - still_bad)
    assert resolved == [], (
        "These grandfathered unparseable tokens now parse cleanly — remove "
        "them from _UNPARSEABLE_GRANDFATHER:\n  " + "\n  ".join(resolved)
    )

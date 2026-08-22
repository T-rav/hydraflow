"""Durable guard against ADR-number corruption (issue #9406).

Two different ADR files sharing one number silently corrupts the runtime
index (``scan_adr_directory`` dedups by number; downstream citation lookups
merge both files' citations), so one ADR's decision silently absorbs the
other's enforcement anchors.
``tests/regressions/test_issue_9406.py`` guards invariant (1) via the live
parser; this module adds the structural invariants that prevent a collision
from being re-introduced and keep the index, headings, cross-links and README
mutually consistent.

Invariants:
  1. Filename-number uniqueness — each ``NNNN`` prefix maps to exactly one file.
  2. Heading == filename — each file's ``# ADR-NNNN`` H1 number matches its name
     (``_TITLE_RE`` in ``adr_index`` prefers the heading number, so a stale
     heading silently re-introduces a collision).
  3. Cross-link integrity — every ``[ADR-NNNN](NNNN-slug.md)`` link under
     ``docs/adr/`` resolves to an existing file whose number matches the link.
  4. README completeness — every ADR file has exactly one README row and no
     number appears twice.
  5. README status consistency — each README row's Status cell matches its ADR
     file's own ``**Status:**`` / ``## Status`` word (#9456). Compared against
     the file's RAW status word, not ``scan_adr_directory``'s normalized status
     (which buckets ``Rejected`` -> ``Unknown``), so ``Rejected``/``Superseded``
     round-trip and 0039/0040 are not false-flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

_FILENAME_RE = re.compile(r"^(\d{4})-.*\.md$")
_HEADING_RE = re.compile(r"^#\s+ADR-(\d{4})\b")
_LINK_RE = re.compile(r"\[ADR-(\d{4})\]\((\d{4})-[^)]+\.md\)")
_README_ROW_RE = re.compile(r"^\|\s*\[(\d{4})\]\((\d{4})-[^)]+\.md\)")


def _adr_files(adr_dir: Path) -> list[Path]:
    return sorted(p for p in adr_dir.glob("*.md") if _FILENAME_RE.match(p.name))


def test_adr_filename_numbers_are_unique(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    by_number: dict[str, list[str]] = {}
    for path in _adr_files(adr_dir):
        num = _FILENAME_RE.match(path.name).group(1)  # type: ignore[union-attr]
        by_number.setdefault(num, []).append(path.name)

    collisions = {n: names for n, names in by_number.items() if len(names) > 1}
    assert collisions == {}, (
        f"ADR filename numbers must be unique. Collisions: {collisions}"
    )


def test_adr_heading_number_matches_filename(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    mismatches: dict[str, str] = {}
    for path in _adr_files(adr_dir):
        file_num = _FILENAME_RE.match(path.name).group(1)  # type: ignore[union-attr]
        first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
        m = _HEADING_RE.match(first_line)
        if m is None:
            mismatches[path.name] = f"H1 is not '# ADR-NNNN ...': {first_line!r}"
        elif m.group(1) != file_num:
            mismatches[path.name] = f"heading ADR-{m.group(1)} != filename {file_num}"

    assert mismatches == {}, f"ADR heading/filename number mismatches: {mismatches}"


def test_adr_cross_links_resolve(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    broken: list[str] = []
    for path in _adr_files(adr_dir):
        for link_num, file_num in _LINK_RE.findall(path.read_text(encoding="utf-8")):
            if link_num != file_num:
                broken.append(
                    f"{path.name}: link text ADR-{link_num} but target {file_num}-*.md"
                )
                continue
            if not list(adr_dir.glob(f"{file_num}-*.md")):
                broken.append(f"{path.name}: link to {file_num}-*.md (no such file)")

    assert broken == [], "Broken ADR cross-links:\n  " + "\n  ".join(broken)


def test_readme_has_one_row_per_adr(real_repo_root: Path) -> None:
    adr_dir = real_repo_root / "docs" / "adr"
    readme = (adr_dir / "README.md").read_text(encoding="utf-8")

    row_numbers: list[str] = []
    for line in readme.split("\n"):
        m = _README_ROW_RE.match(line)
        if m:
            assert m.group(1) == m.group(2), (
                f"README row number {m.group(1)} != linked file {m.group(2)}-*.md"
            )
            row_numbers.append(m.group(1))

    duplicate_rows = {n for n in row_numbers if row_numbers.count(n) > 1}
    assert duplicate_rows == set(), f"README lists a number twice: {duplicate_rows}"

    file_numbers = {
        _FILENAME_RE.match(p.name).group(1)
        for p in _adr_files(adr_dir)  # type: ignore[union-attr]
    }
    missing = file_numbers - set(row_numbers)
    assert missing == set(), f"ADR files with no README row: {sorted(missing)}"


_README_STATUS_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(\d{4}-[^)]+\.md\)\s*\|[^|]*\|\s*([A-Za-z]+)\s*\|"
)
_STATUS_INLINE_RE = re.compile(r"^\*\*Status:\*\*\s*(\w+)", re.MULTILINE)
_STATUS_H2_RE = re.compile(r"^##\s*Status\s*\n+\s*[-*]?\s*\*?\*?(\w+)", re.MULTILINE)


def _file_raw_status(path: Path) -> str | None:
    """The ADR file's own status WORD (raw, not normalized).

    Handles ``**Status:** X`` and the ``## Status`` section form. ``Superseded
    by ADR-NNNN`` collapses to ``Superseded``. Returns None if unparseable.
    """
    text = path.read_text(encoding="utf-8")
    m = _STATUS_INLINE_RE.search(text) or _STATUS_H2_RE.search(text)
    return m.group(1) if m else None


def test_readme_status_matches_file(real_repo_root: Path) -> None:
    """Each README Status cell matches its ADR file's own status word (#9456)."""
    adr_dir = real_repo_root / "docs" / "adr"
    readme = (adr_dir / "README.md").read_text(encoding="utf-8")

    drift: list[str] = []
    for line in readme.split("\n"):
        m = _README_STATUS_ROW_RE.match(line)
        if not m:
            continue
        num, row_status = m.group(1), m.group(2)
        files = list(adr_dir.glob(f"{num}-*.md"))
        if not files:
            continue  # completeness is covered by test_readme_has_one_row_per_adr
        file_status = _file_raw_status(files[0])
        if file_status and file_status.lower() != row_status.lower():
            drift.append(
                f"ADR-{num}: README says '{row_status}' but file says '{file_status}'"
            )

    assert drift == [], "README Status column drifts from ADR files:\n  " + "\n  ".join(
        drift
    )

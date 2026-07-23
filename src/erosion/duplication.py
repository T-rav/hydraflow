"""Pure duplication-density sensor (#10367, v2 of epic #10104).

The near-duplicate-block signal ``erosion.scatter`` v1 explicitly deferred
(jscpd-class detection — see that module's docstring). Same purity contract
as ``erosion.spread.compute``: ``compute`` reads an explicit mapping of file
contents (NOT a repo root) and returns a ``DuplicationFinding``, so it is
unit-testable with synthetic inputs and has no git dependency in the core.
``duplication_for_range`` is the thin git+fs adapter that materializes file
contents for a real commit range; ``compute`` itself never shells out.

Heuristic (v1, PROVISIONAL): each file is normalized to its sequence of
non-blank, whitespace-collapsed lines; every window of ``block_lines``
consecutive normalized lines is hashed; a window hash appearing in two or
more distinct locations is a duplicated block. Density is duplicated blocks
per KLOC of non-blank lines. Deliberately structural (no token/AST parse) so
it is deterministic and cheap; a future revision may adopt a real jscpd-style
detector.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from erosion.models import DuplicationFinding

_DEFAULT_BLOCK_LINES = 5


def _normalized_lines(text: str) -> list[str]:
    """Non-blank lines with collapsed internal whitespace (order-preserving)."""
    out: list[str] = []
    for raw in text.splitlines():
        collapsed = " ".join(raw.split())
        if collapsed:
            out.append(collapsed)
    return out


def _window_hash(lines: list[str]) -> str:
    joined = "\n".join(lines)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compute(
    files: dict[str, str], *, block_lines: int = _DEFAULT_BLOCK_LINES
) -> DuplicationFinding:
    """Pure: near-duplicate block density over explicit file contents. No I/O.

    *files* maps a path (repo-root-relative in real use; any label in tests)
    to its full text. A block is ``block_lines`` consecutive non-blank
    normalized lines; a block hash occurring at two or more distinct
    (file, offset) locations counts once as a duplicated block, and each such
    group records the sorted set of files it spans.
    """
    locations: dict[str, list[str]] = defaultdict(list)
    total_lines = 0
    for path, text in files.items():
        lines = _normalized_lines(text)
        total_lines += len(lines)
        if len(lines) < block_lines:
            continue
        for start in range(0, len(lines) - block_lines + 1):
            window = lines[start : start + block_lines]
            locations[_window_hash(window)].append(path)

    duplicated_blocks = 0
    groups: list[tuple[str, ...]] = []
    for _digest, paths in locations.items():
        if len(paths) >= 2:
            duplicated_blocks += 1
            groups.append(tuple(sorted(set(paths))))

    return DuplicationFinding(
        duplicated_blocks=duplicated_blocks,
        total_lines=total_lines,
        block_lines=block_lines,
        duplicate_groups=tuple(sorted(groups)),
    )


def duplication_for_range(
    repo_root: Path,
    changed_files: list[str],
    *,
    block_lines: int = _DEFAULT_BLOCK_LINES,
) -> DuplicationFinding | None:
    """Compute duplication density over the current contents of *changed_files*.

    Thin fs adapter — NOT part of the pure sensor. Reads each ``.py`` file's
    current on-disk contents (best-effort; unreadable/missing files are
    skipped) and delegates to ``compute``. Returns ``None`` only on a
    catastrophic read failure of the whole set; an empty set yields an empty
    finding.
    """
    contents: dict[str, str] = {}
    for rel in changed_files:
        if not rel.endswith(".py"):
            continue
        try:
            contents[rel] = (repo_root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return compute(contents, block_lines=block_lines)

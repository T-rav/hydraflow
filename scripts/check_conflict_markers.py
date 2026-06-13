"""Fail if any file contains a leftover git conflict marker.

Conflict markers committed to the repo are a recurring corruption vector: #9422
merged raw markers into 11 ``docs/wiki/terms/*.md`` files because the (pre-#9475)
bot-PR auto-heal committed a conflicted merge, and **no check rejected them** —
they passed every gate and reached ``staging`` (#9482). This guard closes that
hole universally: it runs in pre-commit (over staged files) and in CI (over the
whole tracked tree), so a marker can never reach a branch again regardless of
which path produced it.

Detection is deliberately conservative to avoid false positives. A real conflict
is identified by an opening (``<`` x7), base (``|`` x7), or closing (``>`` x7)
marker **at the start of a line**, followed by a space/tab or end-of-line — the
exact shapes ``git`` writes. The ``=`` x7 separator is intentionally NOT matched
on its own: it collides with Markdown setext headings and reStructuredText
underlines, whereas the angle/pipe markers never legitimately begin a line.

Usage:
    check_conflict_markers.py <file> [<file> ...]   # scan the given paths
    check_conflict_markers.py --tracked             # scan all git-tracked files
    check_conflict_markers.py                       # same as --tracked
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Opening / base / closing markers (7 chars) at line start, then space|tab|EOL.
_MARKER = re.compile(r"^(<{7}|>{7}|\|{7})([ \t]|$)")


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def scan(paths: list[str], root: Path) -> list[tuple[str, int, str]]:
    """Return (relpath, line_number, snippet) for every conflict marker found."""
    hits: list[tuple[str, int, str]] = []
    for rel in paths:
        path = (root / rel) if not Path(rel).is_absolute() else Path(rel)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — not a text conflict
        for num, line in enumerate(text.splitlines(), start=1):
            if _MARKER.match(line):
                hits.append((rel, num, line[:72]))
    return hits


def main(argv: list[str]) -> int:
    root = _repo_root()
    file_args = [a for a in argv if a != "--tracked"]
    paths = (
        _tracked_files(root) if ("--tracked" in argv or not file_args) else file_args
    )

    hits = scan(paths, root)
    if hits:
        print(
            "git conflict markers found — refusing to proceed "
            "(resolve them, then re-run):",
            file=sys.stderr,
        )
        for rel, num, snippet in hits:
            print(f"  {rel}:{num}: {snippet}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Pre-push advisory: warn about uncommitted tests/regressions/ contract files.

Surface 2 of #9597 (absorbed #9873): StaleIssueLoop's regression-rot check
(``src/stale_issue_loop.py``) only sees *committed* regression-test files —
a deployed caretaker loop cannot see a dev checkout's working tree. But the
2026-06-13 incident that motivated #9597 was exactly that: 12 RED regression
tests sat *uncommitted* in a dev checkout with their issues still open, and
nothing warned before the work was pushed/lost.

This script covers that half: it looks for untracked or modified
``tests/regressions/*_issue_<N>*.py`` files and prints an advisory warning
listing them + their issue numbers. It is deliberately offline (only
``git status --porcelain`` — no ``gh``, no network) and fast, and it never
fails the push — see ``main()``.

Reuses :func:`regression_rot_scan.parse_issue_numbers` so the naming
convention has one source of truth shared with the committed-tree detector.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from regression_rot_scan import parse_issue_numbers  # noqa: E402


def find_uncommitted_regression_paths(porcelain: str) -> list[str]:
    """Extract ``tests/regressions/*.py`` paths from ``git status --porcelain``.

    Handles untracked (``??``), modified (`` M``/``M ``/``MM``), and renamed
    (``R  old -> new``) entries; renamed entries report the destination path.
    Paths outside ``tests/regressions/`` or not ending in ``.py`` are
    excluded.
    """
    paths: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        status, rest = line[:2], line[3:]
        if "R" in status and " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        rest = rest.strip().strip('"')
        if rest.startswith("tests/regressions/") and rest.endswith(".py"):
            paths.append(rest)
    return paths


def build_warning(paths: list[str]) -> str | None:
    """Return the advisory warning text for *paths*, or ``None`` if none warrant one.

    Only paths whose filename matches the ``{test,regression}_issue_<N>``
    convention are reported — descriptively-named regression files carry no
    parseable issue number and are silently skipped (same precision rule as
    the committed-tree detector).
    """
    entries: list[tuple[str, list[int]]] = []
    for rel_path in paths:
        stem = Path(rel_path).stem
        issue_numbers = parse_issue_numbers(stem)
        if issue_numbers:
            entries.append((rel_path, issue_numbers))

    if not entries:
        return None

    lines = [
        "",
        "pre-push WARNING: uncommitted tests/regressions/ contract file(s):",
    ]
    for rel_path, numbers in entries:
        issues = ", ".join(f"#{n}" for n in numbers)
        lines.append(f"  {rel_path}  (issue {issues})")
    lines += [
        "  These files are not committed. If the work is lost, a written-but-",
        "  unimplemented contract silently rots with no guard watching it (the",
        "  2026-06-13 incident behind #9597). Commit them before pushing.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "tests/regressions"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        paths = find_uncommitted_regression_paths(result.stdout)
        warning = build_warning(paths)
        if warning:
            print(warning)
    except Exception as exc:  # noqa: BLE001 - advisory check must never block a push
        print(f"pre-push: regression-rot check skipped ({exc})", file=sys.stderr)
    return 0  # always 0 — advisory only


if __name__ == "__main__":
    sys.exit(main())

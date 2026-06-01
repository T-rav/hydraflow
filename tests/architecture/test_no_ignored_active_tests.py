"""Guard active pytest coverage against ignored tests."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = ROOT / "tests"

IGNORED_TEST_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("skip marker", re.compile(r"pytest\.mark\.skip|pytest\.mark\.skipif")),
    ("runtime skip", re.compile(r"pytest\.skip\(")),
    ("xfail marker", re.compile(r"pytest\.mark\.xfail|pytest\.xfail\(")),
    ("unittest skip", re.compile(r"unittest\.skip|@skip")),
    (
        "commented-out test/assertion",
        re.compile(
            r"^\s*#\s*("
            r"async\s+def\s+test_|"
            r"def\s+test_|"
            r"class\s+Test|"
            r"@pytest\.mark|"
            r"pytestmark\s*=|"
            r"assert\s+"
            r")"
        ),
    ),
)


def _active_test_files() -> list[Path]:
    this_file = Path(__file__).resolve()
    return sorted(
        path
        for path in TESTS_ROOT.rglob("*.py")
        if path.resolve() != this_file
        and (path.name.startswith("test") or path.name == "conftest.py")
    )


def test_active_tests_do_not_skip_xfail_or_comment_out_coverage() -> None:
    offenders: list[str] = []
    for path in _active_test_files():
        rel = path.relative_to(ROOT)
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            for label, pattern in IGNORED_TEST_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{rel}:{line_no}: {label}: {line.strip()}")

    assert not offenders, (
        "Active tests must assert real contracts. Move deferred work to bd or "
        "out of pytest collection; do not hide it behind skip/xfail/commented "
        "tests:\n  " + "\n  ".join(offenders)
    )

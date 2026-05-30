"""Guardrails against screenshot/pixel-baseline regression tests.

HydraFlow still supports operator bug-report screenshots. This guard only
prohibits screenshot images as an automated quality oracle. UI coverage should
assert semantic DOM/API behavior through MockWorld and Playwright scenarios.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATTERNS = (
    "toHaveScreenshot",
    ".to_have_screenshot",
    "page.screenshot(",
    "expect(page).toHaveScreenshot",
    "npm run screenshot",
)

FORBIDDEN_PATH_PARTS = {
    "__snapshots__",
}

IGNORED_DIR_PARTS = {
    ".git",
    ".hydraflow",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".uv-cache",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
    "site",
}

IGNORED_FILES = {
    "test_no_screenshot_regression_tests.py",
}


def _candidate_files() -> list[Path]:
    candidates: list[Path] = []
    for base in (ROOT / "tests", ROOT / "src" / "ui", ROOT / ".github"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = set(path.relative_to(ROOT).parts)
            if rel_parts & IGNORED_DIR_PARTS:
                continue
            if path.name in IGNORED_FILES:
                continue
            if path.suffix.lower() not in {
                ".cjs",
                ".js",
                ".jsx",
                ".mjs",
                ".py",
                ".ts",
                ".tsx",
                ".yml",
                ".yaml",
            }:
                continue
            candidates.append(path)
    return sorted(candidates)


def test_no_screenshot_snapshot_directories_are_tracked() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("*")
        if path.is_dir()
        and any(part in FORBIDDEN_PATH_PARTS for part in path.relative_to(ROOT).parts)
        and not (set(path.relative_to(ROOT).parts) & IGNORED_DIR_PARTS)
    ]

    assert offenders == [], (
        "Screenshot snapshot directories are not trusted test artifacts. "
        f"Remove them and cover the behavior semantically: {offenders}"
    )


@pytest.mark.parametrize(
    "path", _candidate_files(), ids=lambda p: p.relative_to(ROOT).as_posix()
)
def test_no_pixel_screenshot_assertions(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    found = [pattern for pattern in FORBIDDEN_PATTERNS if pattern in text]

    assert found == [], (
        f"{path.relative_to(ROOT)} contains screenshot/pixel-baseline test hooks "
        f"{found}. Use semantic MockWorld, DOM, API, or sandbox assertions instead."
    )

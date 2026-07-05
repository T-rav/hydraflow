# src/auto_tighten/coverage_adapter.py
from __future__ import annotations

import re
from pathlib import Path

from auto_tighten.models import CoverageRecord, FileEdit

_FAIL_UNDER = re.compile(
    r"^(?P<pre>\s*fail_under\s*=\s*)(?P<val>[0-9]+(?:\.[0-9]+)?)", re.MULTILINE
)


class CoverageAdapter:
    ratchet_id = "coverage"

    def __init__(self, *, coverage_jsonl: Path, margin: float) -> None:
        self._cov = coverage_jsonl
        self._margin = margin

    def current(self, repo_root: Path) -> float:
        lines = (
            [line for line in self._cov.read_text().splitlines() if line.strip()]
            if self._cov.exists()
            else []
        )
        if not lines:
            raise FileNotFoundError("no recorded coverage yet")
        return CoverageRecord.model_validate_json(lines[-1]).coverage_percent

    def baseline(self, repo_root: Path) -> float:
        text = (repo_root / "pyproject.toml").read_text()
        m = _FAIL_UNDER.search(text)
        if not m:
            raise ValueError("fail_under not found in pyproject.toml")
        return float(m.group("val"))

    def is_tighter(self, a: float, b: float) -> bool:
        return a > b

    def weakest(self, a: float, b: float) -> float:
        return min(a, b)

    def apply_margin(self, floor: float) -> float:
        return round(floor - self._margin, 1)

    def render_tightened(self, repo_root: Path, value: float) -> list[FileEdit]:
        path = repo_root / "pyproject.toml"
        text = path.read_text()
        new_val = int(value) if float(value).is_integer() else value
        new_text = _FAIL_UNDER.sub(
            lambda m: f"{m.group('pre')}{new_val}", text, count=1
        )
        return [FileEdit(path=str(path), new_text=new_text)]

    def dedup_key(self, value: float) -> str:
        return f"coverage:{value:.1f}"

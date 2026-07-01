"""Suppression-count detector: `# type: ignore` / `# noqa` across src/."""

from __future__ import annotations

import re
from pathlib import Path

from disturbance.models import Finding

_SUPPRESSION_RE = re.compile(
    r"#\s*(?P<kind>type:\s*ignore|noqa)(?P<detail>\[[^\]]*\]|:\s*[^\s#]+)?"
)


def _normalize(kind: str, detail: str | None) -> str:
    base = "type-ignore" if kind.replace(" ", "").startswith("type") else "noqa"
    tail = (detail or "").replace(" ", "")
    return f"{base}{tail}"


class SuppressionsDetector:
    name = "suppressions"

    def __init__(self, globs: tuple[str, ...] = ("src/**/*.py",)) -> None:
        self._globs = globs

    def detect(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[Path] = set()
        for glob in self._globs:
            for path in sorted(repo_root.glob(glob)):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                findings.extend(self._scan(repo_root, path))
        return findings

    def _scan(self, repo_root: Path, path: Path) -> list[Finding]:
        rel = path.relative_to(repo_root).as_posix()
        out: list[Finding] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _SUPPRESSION_RE.search(line)
            if not m:
                continue
            code = _normalize(m.group("kind"), m.group("detail"))
            out.append(
                Finding(
                    dimension="suppressions",
                    path=rel,
                    signature=f"{rel}::{code}",
                    message=f"suppression `{m.group(0).strip()}`",
                )
            )
        return out

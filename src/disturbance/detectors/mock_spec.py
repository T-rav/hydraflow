"""Mock-spec detector: adapts the existing AST detector into the dampener framework.

Reuses `src/_mock_spec_detector.py` rather than duplicating the AST logic.
"""

from __future__ import annotations

from pathlib import Path

from _mock_spec_detector import detect_violations
from disturbance.models import Finding

_FIXTURE_MARKER = "_mock_spec_fixtures"


class MockSpecDetector:
    name = "mock_spec"

    def __init__(self, globs: tuple[str, ...] = ("tests/**/test_*.py",)) -> None:
        self._globs = globs

    def detect(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[Path] = set()
        for glob in self._globs:
            for path in sorted(repo_root.glob(glob)):
                if path in seen or not path.is_file():
                    continue
                if (
                    _FIXTURE_MARKER in path.parts
                ):  # synthetic fixtures contain violations by design
                    continue
                seen.add(path)
                rel = path.relative_to(repo_root).as_posix()
                for v in detect_violations(path):
                    findings.append(
                        Finding(
                            dimension="mock_spec",
                            path=rel,
                            signature=f"{rel}::mock_spec",
                            message=v.reason,
                        )
                    )
        return findings

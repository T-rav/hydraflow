"""The ViolationDetector protocol (the Sensor role, ADR-0094)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from disturbance.models import Finding


class ViolationDetector(Protocol):
    name: str

    def detect(self, repo_root: Path) -> list[Finding]:
        """Return all current findings for this dimension. Pure: reads files only."""
        ...

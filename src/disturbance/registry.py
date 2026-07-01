"""Dimension registry: each dimension binds a detector, a baseline, and a fix prompt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from disturbance.detectors.base import ViolationDetector
from disturbance.detectors.mock_spec import MockSpecDetector
from disturbance.detectors.suppressions import SuppressionsDetector

BASELINE_DIR = Path("disturbance/baselines")


@dataclass(frozen=True)
class DimensionSpec:
    name: str
    detector: ViolationDetector
    baseline_path: Path
    fix_prompt: str


DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(
        name="mock_spec",
        detector=MockSpecDetector(),
        baseline_path=BASELINE_DIR / "mock_spec.yaml",
        fix_prompt=(
            "Add an explicit `spec=` to the Mock (or type the variable with the real "
            "Port and pass `spec=ThatPort`) so the mock cannot grow undeclared attributes."
        ),
    ),
    DimensionSpec(
        name="suppressions",
        detector=SuppressionsDetector(),
        baseline_path=BASELINE_DIR / "suppressions.yaml",
        fix_prompt=(
            "Remove the `# type: ignore` / `# noqa` and fix the underlying type or lint "
            "error. If it is genuinely unavoidable, narrow it to a specific code and add a "
            "one-line justification; never blanket-suppress."
        ),
    ),
]

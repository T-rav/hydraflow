"""Dimension registry: each dimension binds a detector, a baseline, and a fix prompt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from disturbance.detectors.base import ViolationDetector
from disturbance.detectors.mock_spec import MockSpecDetector
from disturbance.detectors.suppressions import SuppressionsDetector
from disturbance.detectors.traceability import TraceabilityDetector

BASELINE_DIR = Path("disturbance/baselines")


@dataclass(frozen=True)
class DimensionSpec:
    name: str
    detector: ViolationDetector
    baseline_path: Path
    fix_prompt: str
    # Whether the DisturbanceDampenerLoop may dispatch burn-down PRs for this
    # dimension's backlog. Adoption-style ratchets (e.g. traceability, whose
    # findings live in a generated artifact and shrink only when future work
    # threads requirement IDs) opt out: an agent cannot "fix" them in place.
    burn_down: bool = True


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
    DimensionSpec(
        name="traceability",
        detector=TraceabilityDetector(),
        baseline_path=BASELINE_DIR / "traceability.yaml",
        fix_prompt=(
            "Thread requirement IDs through recent work: add a `req:<id>` label (or a "
            "`Req-ID:` body line) to the driving issue so the planner, PR body, and "
            "commit trailers carry it, then regenerate the traceability matrix "
            "(`make arch-regen`) and prune this baseline to the new, lower "
            "untraced percentage. The fraction may only shrink."
        ),
        burn_down=False,
    ),
]

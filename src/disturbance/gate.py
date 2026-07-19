"""The feedforward ratchet gate (block-new + keep baseline honest)."""

from __future__ import annotations

from pathlib import Path

from disturbance.baseline import diff, load_baseline
from disturbance.models import RatchetResult
from disturbance.registry import DIMENSIONS, DimensionSpec


def run_gate(
    repo_root: Path, dimensions: list[DimensionSpec] | None = None
) -> dict[str, RatchetResult]:
    specs = dimensions if dimensions is not None else DIMENSIONS
    results: dict[str, RatchetResult] = {}
    for spec in specs:
        current = spec.detector.detect(repo_root)
        baseline = load_baseline(
            spec.baseline_path
            if spec.baseline_path.is_absolute()
            else repo_root / spec.baseline_path
        )
        results[spec.name] = diff(current, baseline)
    return results

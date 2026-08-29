"""The feedforward ratchet gate (block-new + keep baseline honest)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from disturbance.baseline import diff, load_baseline
from disturbance.models import RatchetResult
from disturbance.registry import DIMENSIONS, DimensionSpec

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping
    from pathlib import Path


class DeadRatchetArmError(RuntimeError):
    """A baseline sits where its dimension's block-new arm can never fire.

    The gate blocks on ``cur > base``. When a signature's baseline is at or
    above the largest count its detector can reach, no input reddens it: the
    failing region is EMPTY and the dimension reports a clean ratchet while
    blocking nothing. That is how the traceability dimension shipped — a
    detector clamped at 100 against a baseline of 100 (#9733) — and nothing
    in the repo noticed for the life of the dimension.

    Raised rather than reported so the configuration cannot be run past.
    """


def dead_ratchet_arms(spec: DimensionSpec, baseline: Mapping[str, int]) -> list[str]:
    """Baseline entries of *spec* whose block-new arm is arithmetically dead.

    Pure, and separate from :func:`run_gate` so the predicate can be asserted
    directly on known-dead and known-live configurations rather than only
    through whatever the live baselines happen to hold today.
    """
    ceilings = spec.detector.reachable_ceilings()
    dead: list[str] = []
    for signature, count in sorted(baseline.items()):
        ceiling = ceilings.get(signature)
        if ceiling is None:
            continue  # unbounded: some reachable count always exceeds the baseline
        if count >= ceiling:
            dead.append(
                f"{spec.name}: baseline {signature!r} is {count}, but the "
                f"detector can never emit more than {ceiling} findings for it. "
                "The block-new arm cannot fire — the failing region is empty. "
                "Lower the baseline, raise the detector's reachable ceiling, or "
                "measure something whose range extends past the baseline."
            )
    return dead


def _assert_arms_can_fire(
    specs: list[DimensionSpec], baselines: list[dict[str, int]]
) -> None:
    dead = [
        message
        for spec, baseline in zip(specs, baselines, strict=True)
        for message in dead_ratchet_arms(spec, baseline)
    ]
    if dead:
        raise DeadRatchetArmError(
            "ratchet baselines sit outside their detectors' reachable range:\n"
            + "\n".join(f"  - {m}" for m in dead)
        )


def run_gate(
    repo_root: Path, dimensions: list[DimensionSpec] | None = None
) -> dict[str, RatchetResult]:
    specs = dimensions if dimensions is not None else DIMENSIONS
    baselines = [
        load_baseline(
            spec.baseline_path
            if spec.baseline_path.is_absolute()
            else repo_root / spec.baseline_path
        )
        for spec in specs
    ]
    # Before measuring anything: refuse a threshold that sits outside the
    # range its own detector can reach. A gate whose failing region is empty
    # is not a passing gate, and reporting it as one is the defect.
    _assert_arms_can_fire(specs, baselines)
    results: dict[str, RatchetResult] = {}
    for spec, baseline in zip(specs, baselines, strict=True):
        current = spec.detector.detect(repo_root)
        results[spec.name] = diff(current, baseline)
    return results

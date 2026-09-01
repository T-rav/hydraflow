"""Version-controlled set-point for the suite-time sensor (#11910).

Mirrors ``erosion.suite_hygiene_baseline``'s shrink-only shape, with one
deliberate departure that the other baselines do not have to think about:
**this sensor measures, it does not parse.**

LOC and parametrize-copy counts are deterministic — the same tree gives the
same number on any machine, so gating a rise is safe. Duration is not. The
same test measured 32s alone and 90s under a loaded host during this issue's
own investigation, a 3x swing with no code change. A gate on raw seconds would
fire on contention, get diagnosed as a flake, and be switched off — the failure
mode this repo has already paid for elsewhere.

So the gate is on **share**: the fraction of measured runtime held by the slow
tests. Contention inflates every duration together, so the ratio survives it
while an absolute reading does not. ``tolerance`` then absorbs the residual
non-uniformity (one test contended harder than its neighbours), and the gate
still catches the thing worth catching — a test that has come to dominate the
suite relative to everything else.

Per-test seconds ARE recorded, but only so the roster can report growth. They
are never gated, for exactly the reason above.

YAML shape::

    comment: "<why the set-point last moved>"
    threshold_seconds: 10.0
    max_slow_share: 0.146
    tolerance: 0.10
    slow_tests:
      tests/architecture/test_x.py::test_y: 18.8
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from erosion.models import SlownessFinding

#: Share may rise this far above the mark before the gate fires. Absorbs the
#: non-uniform part of host contention; a real regression moves it much further.
DEFAULT_TOLERANCE = 0.10


@dataclass(frozen=True)
class SlownessBaseline:
    """The recorded suite-time set-point."""

    max_slow_share: float | None = None
    threshold_seconds: float | None = None
    tolerance: float = DEFAULT_TOLERANCE
    slow_tests: dict[str, float] = field(default_factory=dict)
    comment: str = ""

    @property
    def is_empty(self) -> bool:
        return self.max_slow_share is None


def load_slowness_baseline(path: Path) -> SlownessBaseline:
    """Read the set-point. A missing or malformed file yields an EMPTY baseline.

    Empty means "never recorded", and :func:`exceeded` returns nothing for it —
    a repo that has not set a mark cannot have regressed against one.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return SlownessBaseline()
    if not isinstance(raw, dict):
        return SlownessBaseline()
    share = raw.get("max_slow_share")
    tests = raw.get("slow_tests")
    return SlownessBaseline(
        max_slow_share=float(share) if isinstance(share, int | float) else None,
        threshold_seconds=(
            float(raw["threshold_seconds"])
            if isinstance(raw.get("threshold_seconds"), int | float)
            else None
        ),
        tolerance=(
            float(raw["tolerance"])
            if isinstance(raw.get("tolerance"), int | float)
            else DEFAULT_TOLERANCE
        ),
        slow_tests={
            str(k): float(v)
            for k, v in (tests or {}).items()
            if isinstance(v, int | float)
        }
        if isinstance(tests, dict)
        else {},
        comment=str(raw.get("comment", "")),
    )


def save_slowness_baseline(
    path: Path, finding: SlownessFinding, *, comment: str, tolerance: float
) -> None:
    """Write the set-point from a live reading — a deliberate, reviewed act."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "comment": comment,
                "threshold_seconds": round(finding.threshold_seconds, 3),
                "max_slow_share": round(finding.share, 4),
                "tolerance": round(tolerance, 3),
                "slow_tests": {
                    t.nodeid: round(t.seconds, 2) for t in finding.slow_tests
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def exceeded(finding: SlownessFinding, baseline: SlownessBaseline) -> tuple[str, ...]:
    """Messages for each way *finding* regressed past *baseline*.

    Returns nothing when the baseline is empty (never recorded) or the reading
    is unmeasured (``total_tests == 0``). Those are not clean bills of health —
    they are absences of evidence — and the caller is expected to say so rather
    than treat silence here as a pass.
    """
    if baseline.is_empty or finding.total_tests == 0:
        return ()
    assert baseline.max_slow_share is not None
    ceiling = baseline.max_slow_share + baseline.tolerance
    if finding.share > ceiling:
        return (
            f"slow-test share {finding.share:.1%} > baseline "
            f"{baseline.max_slow_share:.1%} + {baseline.tolerance:.0%} tolerance. "
            f"{len(finding.slow_tests)} test(s) over "
            f"{finding.threshold_seconds:.0f}s now hold "
            f"{finding.slow_seconds:.0f}s of {finding.total_seconds:.0f}s.",
        )
    return ()

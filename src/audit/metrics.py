"""Pure metrics for the sampled re-audit (#10370).

All functions are pure over ``list[AuditSample]`` so the headline falsification
metric renders identically by the report and the dashboard:

* **disagreement rate with a Wilson-score confidence interval** — the headline:
  a statistical bound on the undetected escape rate (a proportion CI, not a bare
  point estimate, because the sample is small by design);
* **auditor false-alarm rate** — refuted disagreements over adjudicated ones;
  keeps the instrument honest in the other direction (an auditor that cries wolf
  gets rationally dismissed);
* **per-gate-class calibration** — which blast-radius class the disagreements /
  upheld escapes implicate, feeding ``DetectorCalibrationLoop``'s territory.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from audit.models import (
    AuditSample,
    CalibrationSummary,
    GateClassCalibration,
    RateCI,
)

# Wilson-score z for a 95% two-sided interval.
_WILSON_Z = 1.96


def wilson_interval(successes: int, n: int, *, z: float = _WILSON_Z) -> RateCI:
    """Wilson-score interval for a binomial proportion.

    Chosen over the normal approximation because the audit sample is small by
    design (sampling is the point), where Wald intervals misbehave near 0/1.
    Returns a degenerate ``[0, 0]`` at ``n == 0``.
    """
    if n <= 0:
        return RateCI(rate=0.0, lower=0.0, upper=0.0, n=0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return RateCI(rate=p, lower=lower, upper=upper, n=n)


def disagreement_rate_ci(samples: list[AuditSample]) -> RateCI:
    """Headline: disagreement proportion + Wilson CI over all audited samples."""
    n = len(samples)
    disagreements = sum(1 for s in samples if s.verdict == "disagree")
    return wilson_interval(disagreements, n)


def false_alarm_rate(samples: list[AuditSample]) -> float:
    """Refuted disagreements / adjudicated disagreements (``0.0`` when none).

    Only ``upheld`` + ``refuted`` rows are adjudicated; ``pending`` disagreements
    are not yet counted either way, keeping the rate honest.
    """
    adjudicated = [s for s in samples if s.disposition in ("upheld", "refuted")]
    if not adjudicated:
        return 0.0
    refuted = sum(1 for s in adjudicated if s.disposition == "refuted")
    return refuted / len(adjudicated)


def per_gate_class_calibration(
    samples: list[AuditSample],
) -> list[GateClassCalibration]:
    """Sampled / disagreement / upheld counts per blast-radius class, sorted."""
    sampled: dict[str, int] = defaultdict(int)
    disagreements: dict[str, int] = defaultdict(int)
    upheld: dict[str, int] = defaultdict(int)
    for s in samples:
        cls = s.blast_radius_class
        sampled[cls] += 1
        if s.verdict == "disagree":
            disagreements[cls] += 1
        if s.disposition == "upheld":
            upheld[cls] += 1
    rows = [
        GateClassCalibration(
            blast_radius_class=cls,
            sampled=sampled[cls],
            disagreements=disagreements[cls],
            upheld=upheld[cls],
        )
        for cls in sorted(sampled)
    ]
    return rows


def summarize(
    samples: list[AuditSample], *, governed_rate: float
) -> CalibrationSummary:
    """Roll a full calibration summary for the report + dashboard."""
    return CalibrationSummary(
        disagreement=disagreement_rate_ci(samples),
        false_alarm_rate=false_alarm_rate(samples),
        per_gate_class=per_gate_class_calibration(samples),
        total_samples=len(samples),
        governed_rate=governed_rate,
    )


def calibration_metrics(samples: list[AuditSample]) -> dict[str, Any]:
    """Dashboard/arch render shape for the sampled re-audit (#10370).

    Mirrors ``judge_independence.calibration_metrics``: a flat JSON-safe dict the
    ``/api/diagnostics/gauntlet-calibration`` panel returns and the arch
    generator renders into the sampled-audit live-observations table. The
    governed rate is read from the most recent sample's recorded ``sample_rate``
    (each row records the rate it was sampled at), so the shape needs no state
    handle. Pure over the recorded ledger rows.
    """
    ci = disagreement_rate_ci(samples)
    governed = samples[-1].sample_rate if samples else 0.0
    return {
        "samples": len(samples),
        "disagreement_rate": round(ci.rate, 4),
        "ci_lower": round(ci.lower, 4),
        "ci_upper": round(ci.upper, 4),
        "false_alarm_rate": round(false_alarm_rate(samples), 4),
        "governed_rate": round(governed, 4),
        "per_gate_class": {
            row.blast_radius_class: {
                "sampled": row.sampled,
                "disagreements": row.disagreements,
                "upheld": row.upheld,
            }
            for row in per_gate_class_calibration(samples)
        },
    }

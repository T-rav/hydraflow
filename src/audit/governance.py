"""Shewhart rate governor for the sampled re-audit (#10370).

The sampling rate is GOVERNED, not fixed (decided): widen toward the ceiling
while disagreement runs above its control limit, narrow toward the floor when
quiet. Shewhart's rule applied to the gauntlet — sampling effort follows
observed variation.

``govern_rate`` is pure over the per-tick ``DisagreementObservation`` series. It
is a ONE-SIDED p-chart against a fixed TARGET disagreement rate (the acceptable
adversarial-disagreement noise floor the gauntlet aims to stay under), not a
self-referential pooled mean — a self-referential chart treats a *sustained*
high rate as "in control" and would never climb, which is the opposite of the
spec's intent. So the control limit is anchored to ``TARGET_DISAGREEMENT_RATE``:

* **out-of-control high** (latest subgroup proportion above the target's upper
  control limit) → multiply the rate up toward the ceiling;
* **quiet / in-control** (latest proportion at or below the target) → multiply
  the rate down toward the floor;
* **within the band** (between target and UCL) → hold.

The control limit's sampling variance is based on the POOLED window sample size,
not just the latest subgroup. At realistic per-tick volumes (5% of a handful of
merges = 0-3 samples) a latest-subgroup-only sigma makes the UCL ~0.43-0.70, so
the widen branch almost never fires while every quiet tick narrows — the rate
decays to the floor and rarely widens. Pooling the retained window's samples
gives a stable variance base so sustained real-volume disagreement actually
crosses the limit. (An *average* subgroup n would not help — it just re-derives
the tiny per-tick size; the total pooled n is what tightens the limit.)

The result is always clamped to ``[floor, ceiling]``. Below a minimum pooled
sample count there is not enough signal to move, so the current rate holds
(clamped) — a fresh install does not thrash its rate on one data point.
"""

from __future__ import annotations

import math

from audit.models import DisagreementObservation

# Governance envelope (decided): 2% floor, 20% ceiling, 5% base.
DEFAULT_BASE_RATE = 0.05
DEFAULT_FLOOR = 0.02
DEFAULT_CEILING = 0.20

# The acceptable adversarial-disagreement rate the gauntlet aims to stay under
# (planning-picked v1). The control limit is anchored here so the governor
# responds to the LEVEL of disagreement, not just its variation.
TARGET_DISAGREEMENT_RATE = 0.05

# p-chart control constant (3-sigma is the Shewhart convention) + the
# multiplicative widen/narrow steps and the pooled-sample floor for action.
_SIGMA_K = 3.0
_WIDEN_FACTOR = 1.5
_NARROW_FACTOR = 0.8
_MIN_POOLED_SAMPLES = 5

# How many recent ticks the governor pools + persists (bounded series).
HISTORY_WINDOW = 50


def _clamp(value: float, floor: float, ceiling: float) -> float:
    return max(floor, min(ceiling, value))


def upper_control_limit(
    history: list[DisagreementObservation],
    *,
    target: float = TARGET_DISAGREEMENT_RATE,
) -> float:
    """3-sigma one-sided p-chart UCL around *target*, over the POOLED window.

    Anchored to *target* (not a self-referential pooled mean) so a sustained
    high disagreement rate keeps tripping it. The sampling variance uses the
    POOLED window sample size — the sum of every retained subgroup's ``sampled``
    count — rather than only the latest subgroup: at realistic per-tick volumes
    the latest subgroup is 0-3 samples, whose ``sqrt(1/n)`` sigma is so wide the
    limit never trips. Returns ``target`` when the window carries no samples (no
    data → no sampling variance to add).
    """
    pooled_n = sum(o.sampled for o in history)
    if pooled_n <= 0:
        return target
    sigma = math.sqrt(target * (1.0 - target) / pooled_n)
    return target + _SIGMA_K * sigma


def govern_rate(
    history: list[DisagreementObservation],
    *,
    current_rate: float,
    floor: float = DEFAULT_FLOOR,
    ceiling: float = DEFAULT_CEILING,
    target: float = TARGET_DISAGREEMENT_RATE,
) -> float:
    """Return the next governed sample rate. Pure; always within [floor, ceiling].

    Not enough pooled signal → hold (clamped). Otherwise apply the one-sided
    Shewhart rule against the target's control limit.
    """
    clamped_current = _clamp(current_rate, floor, ceiling)
    if not history:
        return clamped_current
    pooled_n = sum(o.sampled for o in history)
    if pooled_n < _MIN_POOLED_SAMPLES:
        return clamped_current

    latest = history[-1]
    latest_p = latest.proportion
    ucl = upper_control_limit(history, target=target)

    if latest.disagreements > 0 and latest_p > ucl:
        # Special-cause high: disagreement is running hot vs the target — widen.
        return _clamp(clamped_current * _WIDEN_FACTOR, floor, ceiling)
    if latest_p <= target:
        # Quiet / in-control at or below target: narrow sampling toward the floor.
        return _clamp(clamped_current * _NARROW_FACTOR, floor, ceiling)
    return clamped_current


def trim_history(
    history: list[DisagreementObservation], *, window: int = HISTORY_WINDOW
) -> list[DisagreementObservation]:
    """Keep only the most recent *window* observations (bounded persistence)."""
    if window <= 0:
        return []
    return history[-window:]

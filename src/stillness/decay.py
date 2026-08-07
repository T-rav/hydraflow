"""Quiet-week decay curve (#10822) — the stillness acceptance instrument.

The acceptance test for the whole stillness effort, a deliberate re-run of the
accidental two-week quiet (2026-07-14..07-28) that returned churn. Freeze
external intent for a week — the author files nothing; only genuine user-driven
disturbance passes — and measure total *mutating* activity (opened work, PRs,
merges) as a daily series, split by originating signal class:

- **Healthy:** activity decays exponentially to the read-only *sensing floor* —
  the instrument fleet keeps watching, but the actuators go quiet.
- **Unhealthy (hunting):** self-sustaining churn with **zero external input** —
  the factory is its own disturbance source. That is the formal definition of
  hunting, and it is exactly what a settled control system must not do.

This module is the pure measurement engine (``fit_decay``) plus the pure event →
series adapter (``daily_activity``): given classified mutating events it builds
the daily series, fits the decay, and returns a verdict. Reading the on-disk
event log and classifying each event by origin is the runner's job
(``scripts/quiet_week_experiment.py`` — ``make quiet-week``), as is the abort
rule (a genuine incident ends the experiment, and that is fine — an experiment
you cannot abort is a gate you cannot trust).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class SignalClass(StrEnum):
    """Where a day's mutating activity originated."""

    #: Factory-authored work with no external trigger — the churn a quiet week
    #: must see decay. Self-sustaining self-originated activity IS the hunt.
    SELF_ORIGINATED = "self_originated"
    #: Genuine user-driven disturbance (production Sentry from real usage) — the
    #: only input the freeze allows. Its presence excuses non-decaying activity.
    EXTERNAL = "external"


@dataclass(frozen=True)
class DailyActivity:
    """One day of mutating activity, split by originating signal class."""

    day_index: int  # 0-based day within the freeze window
    self_originated: int
    external: int

    @property
    def total(self) -> int:
        return self.self_originated + self.external


class DecayVerdict(StrEnum):
    """The quiet-week outcome — never a blended score."""

    DECAYING = "decaying"  # healthy: activity fell to the sensing floor
    HUNTING = "hunting"  # unhealthy: self-sustaining churn, ~zero external input
    INCONCLUSIVE = "inconclusive"  # neither clearly decayed nor clearly hunting
    INSUFFICIENT_DATA = "insufficient_data"  # window too short to judge


#: A decay-rate (per day) below this is "not really decaying".
DEFAULT_MIN_DECAY_RATE = 0.15
#: Minimum days of series needed before a verdict is trustworthy.
DEFAULT_MIN_DAYS = 4
#: A day's external count at/under this reads as "no external input".
_EXTERNAL_QUIET = 0
#: Multiple of the floor the tail must clear to count as "still above floor".
_ABOVE_FLOOR_FACTOR = 1.5


def _log_linear_decay(
    days: Sequence[int], totals: Sequence[int], floor: float
) -> tuple[float, float]:
    """Least-squares fit of ``log(total - floor)`` vs day → (decay_rate, r²).

    A positive decay rate means activity above the floor is shrinking. r² is the
    goodness of the log-linear fit; a clean exponential decay fits well, noisy
    self-sustaining churn does not. Returns ``(0.0, 0.0)`` when the series has no
    day-to-day spread to fit.
    """
    eps = 1e-9
    ys = [math.log(max(t - floor, eps)) for t in totals]
    n = len(days)
    mean_x = sum(days) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in days)
    if sxx == 0:
        return 0.0, 0.0
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(days, ys, strict=True))
    syy = sum((y - mean_y) ** 2 for y in ys)
    slope = sxy / sxx
    r_squared = (sxy * sxy) / (sxx * syy) if syy > 0 else 1.0
    return -slope, r_squared  # decay_rate = -slope (positive when shrinking)


@dataclass(frozen=True)
class DecayFit:
    """The quiet-week verdict for one freeze window."""

    verdict: DecayVerdict
    decay_rate: float  # per-day exponential rate above the floor (>0 = decaying)
    r_squared: float
    floor: float
    final_total: float
    self_sustaining: bool  # ~zero external input yet self-originated stays high
    n_days: int


def fit_decay(
    series: Sequence[DailyActivity],
    *,
    floor: float,
    min_decay_rate: float = DEFAULT_MIN_DECAY_RATE,
    min_days: int = DEFAULT_MIN_DAYS,
) -> DecayFit:
    """Classify a freeze window as decaying (healthy) or hunting (unhealthy).

    ``floor`` is the read-only sensing floor — the daily activity a fully settled
    factory still shows just by watching. HUNTING is the load-bearing failure:
    external input is quiet across the window, yet self-originated activity does
    not fall to the floor — the factory sustaining its own disturbance. DECAYING
    requires a real decay rate AND a final level back at the floor.
    """
    ordered = sorted(series, key=lambda d: d.day_index)
    n = len(ordered)
    if n < min_days:
        return DecayFit(DecayVerdict.INSUFFICIENT_DATA, 0.0, 0.0, floor, 0.0, False, n)

    days = [d.day_index for d in ordered]
    totals = [d.total for d in ordered]
    decay_rate, r_squared = _log_linear_decay(days, totals, floor)

    final_total = float(totals[-1])
    # "External quiet" over the whole window: no genuine user disturbance came in.
    external_quiet = all(d.external <= _EXTERNAL_QUIET for d in ordered)
    tail_above_floor = ordered[-1].self_originated > floor * _ABOVE_FLOOR_FACTOR
    self_sustaining = (
        external_quiet and tail_above_floor and decay_rate < min_decay_rate
    )

    if self_sustaining:
        verdict = DecayVerdict.HUNTING
    elif decay_rate >= min_decay_rate and final_total <= floor * _ABOVE_FLOOR_FACTOR:
        verdict = DecayVerdict.DECAYING
    else:
        verdict = DecayVerdict.INCONCLUSIVE

    return DecayFit(
        verdict=verdict,
        decay_rate=decay_rate,
        r_squared=r_squared,
        floor=floor,
        final_total=final_total,
        self_sustaining=self_sustaining,
        n_days=n,
    )


# --- event → daily-activity adapter (pure; the runner supplies real events) ---

#: The pipeline event types that count as *mutating* activity — opened work,
#: opened PRs, and merges. Everything else (worker heartbeats, status updates) is
#: sensing, not actuation, so it never enters the decay series.
MUTATING_EVENT_TYPES: frozenset[str] = frozenset(
    {"issue_created", "pr_created", "merge_update"}
)


@dataclass(frozen=True)
class ActivityEvent:
    """One mutating pipeline event, already classified by origin.

    ``day_index`` is 0-based within the freeze window; ``external`` is True for
    genuine user-driven disturbance (a human-filed issue) and False for
    factory-authored activity. The runner does the classification (from the event
    payload / labels) so this adapter stays pure and testable.
    """

    day_index: int
    event_type: str
    external: bool


def daily_activity(
    events: Sequence[ActivityEvent], *, days: int
) -> list[DailyActivity]:
    """Fold classified mutating events into the per-day series ``fit_decay`` reads.

    Non-mutating event types are dropped; events outside ``[0, days)`` are
    ignored. Every day in the window gets a row (zero-filled), so a quiet tail
    reads as decay rather than missing data.
    """
    self_counts = [0] * days
    external_counts = [0] * days
    for event in events:
        if event.event_type not in MUTATING_EVENT_TYPES:
            continue
        if not 0 <= event.day_index < days:
            continue
        if event.external:
            external_counts[event.day_index] += 1
        else:
            self_counts[event.day_index] += 1
    return [
        DailyActivity(
            day_index=i, self_originated=self_counts[i], external=external_counts[i]
        )
        for i in range(days)
    ]

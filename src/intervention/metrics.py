"""Pure intervention-tally metrics (#10369): rate, trust table, span-of-control.

All functions are pure over ``list[InterventionRecord]`` (+ an injected
``now`` / merge count / active-loop count) so the headline attention-side
metrics are unit-testable with synthetic rows and rendered identically by the
report and the dashboard.

The **per-100-merges denominator is IMPORTED from ``escape``**, not
re-derived — the spec makes this deliberate: interventions per 100 merges and
escapes per 100 merges share ONE denominator so the two falsification
instruments are directly comparable and can never drift apart. ``approval`` is
excluded from the correction rate (counted separately) so routine approve/deny
never inflates the signal that measures autonomy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Deliberately-shared denominator (#10369 spec: "same denominator, import/share,
# don't recompute divergently"). ``per_100_merges`` is escape's rate formula
# reused verbatim; ``count_commits_since`` is escape's merge-volume proxy.
from escape.detect import count_commits_since
from escape.metrics import escapes_per_100_merges as per_100_merges
from escape.models import _parse_iso
from intervention.models import CORRECTION_CLASSES, InterventionRecord

__all__ = [
    "MonthlyClassRow",
    "PerLoopRate",
    "by_class",
    "count_commits_since",
    "interventions_per_100_merges",
    "loops_per_governor",
    "model_version_markers",
    "monthly_series",
    "per_100_merges",
    "per_loop_rates",
    "rolling_correction_count",
    "rolling_count",
]


@dataclass(frozen=True)
class PerLoopRate:
    """One loop's/workflow's intervention load — the trust table row."""

    loop_or_workflow: str
    total: int
    correction: int
    approval: int
    per_100_merges: float


@dataclass(frozen=True)
class MonthlyClassRow:
    """One month's intervention counts, split by class (approval separate)."""

    month: str  # "YYYY-MM"
    total: int
    correction: int
    approval: int
    by_class: dict[str, int] = field(default_factory=dict)


def _is_correction(record: InterventionRecord) -> bool:
    return record.intervention_class in CORRECTION_CLASSES


def interventions_per_100_merges(intervention_count: int, merge_count: int) -> float:
    """Interventions per 100 merged changes — the SAME formula as escapes.

    Delegates to ``escape.metrics.escapes_per_100_merges`` (imported) so the
    two instruments cannot diverge; ``0.0`` when no merges are in the window.
    """
    return per_100_merges(intervention_count, merge_count)


def rolling_count(
    records: list[InterventionRecord], now: datetime, *, days: int = 30
) -> int:
    """Count interventions recorded within the last *days* ending at *now*."""
    cutoff = now - timedelta(days=days)
    count = 0
    for r in records:
        ts = _parse_iso(r.ts)
        if ts is not None and cutoff <= ts <= now:
            count += 1
    return count


def rolling_correction_count(
    records: list[InterventionRecord], now: datetime, *, days: int = 30
) -> int:
    """Count CORRECTION-class interventions in the window (approval excluded)."""
    cutoff = now - timedelta(days=days)
    count = 0
    for r in records:
        if not _is_correction(r):
            continue
        ts = _parse_iso(r.ts)
        if ts is not None and cutoff <= ts <= now:
            count += 1
    return count


def by_class(records: list[InterventionRecord]) -> dict[str, int]:
    """Total counts per taxonomy class across the whole ledger."""
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        counts[r.intervention_class] += 1
    return dict(counts)


def per_loop_rates(
    records: list[InterventionRecord], merge_count: int
) -> list[PerLoopRate]:
    """The trust table: per-loop/workflow correction rate per 100 merges.

    ``per_100_merges`` uses the CORRECTION count (approval excluded) against
    the shared denominator — the signal that says which loops earned autonomy.
    Sorted by correction load descending, then name, so the noisiest loops
    surface first.
    """
    totals: dict[str, int] = defaultdict(int)
    corrections: dict[str, int] = defaultdict(int)
    approvals: dict[str, int] = defaultdict(int)
    for r in records:
        key = r.loop_or_workflow or "(unattributed)"
        totals[key] += 1
        if r.intervention_class == "approval":
            approvals[key] += 1
        elif _is_correction(r):
            corrections[key] += 1
    rows = [
        PerLoopRate(
            loop_or_workflow=key,
            total=totals[key],
            correction=corrections[key],
            approval=approvals[key],
            per_100_merges=per_100_merges(corrections[key], merge_count),
        )
        for key in totals
    ]
    rows.sort(key=lambda row: (-row.correction, row.loop_or_workflow))
    return rows


def loops_per_governor(
    active_loop_count: int, daily_correction_interventions: float
) -> float:
    """Loops-per-governor — the factory's span-of-control headline.

    Median concurrently-active worker loops divided by daily correction-class
    interventions (approval excluded, by construction of the numerator the
    caller passes). With zero daily corrections the whole active fleet is
    governed with no correction load, so the span is the active-loop count
    itself (an unbounded ratio would be meaningless — report the fleet size).
    """
    if daily_correction_interventions <= 0:
        return float(active_loop_count)
    return active_loop_count / daily_correction_interventions


def monthly_series(records: list[InterventionRecord]) -> list[MonthlyClassRow]:
    """Interventions bucketed by month (``YYYY-MM``), split by class, ascending."""
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    corrections: dict[str, int] = defaultdict(int)
    approvals: dict[str, int] = defaultdict(int)
    for r in records:
        ts = _parse_iso(r.ts)
        if ts is None:
            continue
        month = f"{ts.year:04d}-{ts.month:02d}"
        buckets[month][r.intervention_class] += 1
        totals[month] += 1
        if r.intervention_class == "approval":
            approvals[month] += 1
        elif _is_correction(r):
            corrections[month] += 1
    return [
        MonthlyClassRow(
            month=month,
            total=totals[month],
            correction=corrections[month],
            approval=approvals[month],
            by_class=dict(buckets[month]),
        )
        for month in sorted(buckets)
    ]


def model_version_markers(
    records: list[InterventionRecord],
) -> list[tuple[str, str]]:
    """First-seen ``(ts, model_version_context)`` for each distinct model.

    These are the change markers annotated onto every trend so trust resets on
    a model upgrade are visible instead of mysterious. Ordered by first-seen
    timestamp; rows with no model context are ignored.
    """
    first_seen: dict[str, str] = {}
    for r in sorted(records, key=lambda x: x.ts):
        model = r.model_version_context.strip()
        if not model or model in first_seen:
            continue
        first_seen[model] = r.ts
    return sorted(((ts, model) for model, ts in first_seen.items()), key=lambda x: x[0])

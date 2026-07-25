"""Pure escape-ledger metrics (#10367): rate, time-to-detection, encoding.

All functions are pure over ``list[EscapeRecord]`` (+ an injected ``now`` /
merge count) so the headline falsification metrics are unit-testable with
synthetic rows and rendered identically by the report and the dashboard:

* **escapes per 100 merges** — the headline falsification metric (rolling
  30-day and monthly series), surfaced BOTH all-confidence and CONFIRMED-only.
  In a fix-heavy repo every ``fix(...): fixes #N`` merge is a low-confidence
  ``bug-issue`` row, so the all-confidence headline conflates ordinary issue
  resolution with real escapes; the confirmed-only rate (high/medium mechanical
  confidence) is the trustworthy number.
* **time-to-detection** — median / p90 (nearest-rank) by detection source
* **encoded-vs-unencoded** — every escape SHOULD terminate in an encoding;
  ``none-yet`` rows aging past a threshold are surfaced for human triage
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from escape.models import EscapeRecord, _parse_iso

#: Mechanical-attribution confidences that count as a CONFIRMED escape. Excludes
#: ``low`` — where the fix-heavy ``bug-issue`` closes land — so the confirmed
#: headline is not inflated by ordinary issue resolution.
CONFIRMED_CONFIDENCES: tuple[str, ...] = ("high", "medium")


@dataclass(frozen=True)
class TtdStat:
    """Time-to-detection summary (hours) for one detection source."""

    n: int
    median_hours: float | None
    p90_hours: float | None


@dataclass(frozen=True)
class EncodedSummary:
    """Encoded-vs-unencoded closure across the ledger."""

    total: int
    encoded: int
    unencoded: int
    by_status: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MonthlyEscapeRow:
    """One month's escape counts, split by detection source."""

    month: str  # "YYYY-MM"
    total: int
    by_source: dict[str, int] = field(default_factory=dict)


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of *sorted_values* (already sorted); ``None`` if empty.

    Uses the nearest-rank ``ceil(pct/100 * n)`` ordinal, not ``round`` — ``round``
    lands one rank low at small n (p90 of 5 values → rank 4 not 5; of 25 → 22
    not 23), understating the tail. Nearest-rank matches the docstring's claim.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, min(len(sorted_values), math.ceil(pct / 100.0 * len(sorted_values))))
    return sorted_values[rank - 1]


def _median(sorted_values: list[float]) -> float | None:
    if not sorted_values:
        return None
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def escapes_per_100_merges(escape_count: int, merge_count: int) -> float:
    """Escapes per 100 merged changes; ``0.0`` when no merges are in the window."""
    if merge_count <= 0:
        return 0.0
    return escape_count / merge_count * 100.0


def is_confirmed(record: EscapeRecord) -> bool:
    """True for a CONFIRMED escape: high/medium mechanical attribution confidence.

    Excludes ``low``-confidence rows — chiefly the ``bug-issue`` ``fix: … fixes
    #N`` closes that dominate a fix-heavy repo — so the confirmed headline counts
    real escapes, not ordinary issue resolution. A derived read over the EXACT
    ledger schema; it changes no record.
    """
    return record.attribution_confidence in CONFIRMED_CONFIDENCES


def confirmed_escapes(records: list[EscapeRecord]) -> list[EscapeRecord]:
    """Subset of *records* that are CONFIRMED escapes (high/medium confidence)."""
    return [r for r in records if is_confirmed(r)]


def rolling_escape_count(
    records: list[EscapeRecord],
    now: datetime,
    *,
    days: int = 30,
    confirmed_only: bool = False,
) -> int:
    """Count escapes detected within the last *days* ending at *now*.

    With ``confirmed_only`` the count includes only high/medium-confidence
    (CONFIRMED) rows, excluding the low-confidence ``bug-issue`` closes that
    would otherwise inflate the headline in a fix-heavy repo.
    """
    cutoff = now - timedelta(days=days)
    count = 0
    for r in records:
        if confirmed_only and not is_confirmed(r):
            continue
        detected = _parse_iso(r.detected_at)
        if detected is not None and cutoff <= detected <= now:
            count += 1
    return count


def rolling_confirmed_escape_count(
    records: list[EscapeRecord], now: datetime, *, days: int = 30
) -> int:
    """CONFIRMED-only rolling escape count — the trustworthy headline numerator."""
    return rolling_escape_count(records, now, days=days, confirmed_only=True)


def time_to_detection_stats(records: list[EscapeRecord]) -> dict[str, TtdStat]:
    """Median/p90 time-to-detection per source (+ ``overall``); populated rows only."""
    by_source: dict[str, list[float]] = defaultdict(list)
    overall: list[float] = []
    for r in records:
        if r.time_to_detection_hours is None:
            continue
        by_source[r.detection_source].append(r.time_to_detection_hours)
        overall.append(r.time_to_detection_hours)

    stats: dict[str, TtdStat] = {}
    for source, values in by_source.items():
        ordered = sorted(values)
        stats[source] = TtdStat(
            n=len(ordered),
            median_hours=_median(ordered),
            p90_hours=_percentile(ordered, 90),
        )
    ordered_all = sorted(overall)
    stats["overall"] = TtdStat(
        n=len(ordered_all),
        median_hours=_median(ordered_all),
        p90_hours=_percentile(ordered_all, 90),
    )
    return stats


def encoded_summary(records: list[EscapeRecord]) -> EncodedSummary:
    """Encoded (terminated in test/lesson/detector/ADR) vs ``none-yet`` counts."""
    by_status: dict[str, int] = defaultdict(int)
    encoded = 0
    unencoded = 0
    for r in records:
        by_status[r.encoded_as] += 1
        if r.encoded_as == "none-yet":
            unencoded += 1
        else:
            encoded += 1
    return EncodedSummary(
        total=len(records),
        encoded=encoded,
        unencoded=unencoded,
        by_status=dict(by_status),
    )


def monthly_series(records: list[EscapeRecord]) -> list[MonthlyEscapeRow]:
    """Escapes bucketed by detection month (``YYYY-MM``), sorted ascending."""
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for r in records:
        detected = _parse_iso(r.detected_at)
        if detected is None:
            continue
        month = f"{detected.year:04d}-{detected.month:02d}"
        buckets[month][r.detection_source] += 1
        totals[month] += 1
    rows: list[MonthlyEscapeRow] = []
    for month in sorted(buckets):
        rows.append(
            MonthlyEscapeRow(
                month=month,
                total=totals[month],
                by_source=dict(buckets[month]),
            )
        )
    return rows


def unencoded_aging(
    records: list[EscapeRecord], now: datetime, *, threshold_hours: float
) -> list[EscapeRecord]:
    """``none-yet`` rows older than *threshold_hours* — the HITL/find surface."""
    aging: list[EscapeRecord] = []
    for r in records:
        if r.encoded_as != "none-yet":
            continue
        detected = _parse_iso(r.detected_at)
        if detected is None:
            continue
        age_h = (now - detected).total_seconds() / 3600.0
        if age_h > threshold_hours:
            aging.append(r)
    return aging


def low_confidence(records: list[EscapeRecord]) -> list[EscapeRecord]:
    """Rows whose mechanical attribution is ``low`` — escalate to HITL."""
    return [r for r in records if r.attribution_confidence == "low"]


def latest_by_id(records: list[EscapeRecord]) -> list[EscapeRecord]:
    """Collapse *records* to one row per id — the latest-appended row wins.

    The ledger is append-only; a human resolution is recorded as a NEW row
    sharing the original's id (``EscapeLedger.append_resolution``). Every
    derived read (rate, encoding, aging) must run through this collapse, or a
    resolved escape is double-counted as both its original and resolved
    state. Order of first appearance in *records* is preserved; the content
    kept per id is whichever record appeared last.
    """
    latest: dict[str, EscapeRecord] = {}
    order: list[str] = []
    for record in records:
        if record.id not in latest:
            order.append(record.id)
        latest[record.id] = record
    return [latest[rid] for rid in order]

"""Read the four instruments' ledgers/series into per-window vitals readings (#10373).

One source of truth: every family reading is computed by IMPORTING the owning
instrument's own pure metric function over its own append-only ledger — never a
divergent re-derivation. A series that has no ledger yet (its instrument is not
built / has never written) reads ``None`` and is skipped, so the verdict
degrades honestly to ``n-of-5 reporting`` instead of counting an absent
instrument as a green vote of confidence. A ledger that EXISTS but is quiet
reads ``0.0`` (present, reporting zero) — the honest distinction between
"nothing to report" and "no instrument".

The readings are windowed by the instruments' own timestamp fields where a
window applies (escapes, interventions, audit, independence) and taken from the
latest monthly trend row for erosion (whose persisted data is month-tagged, not
finely timestamped). Absolute normalisation (e.g. per-100-merges) is
deliberately NOT applied here: the divergence chart compares each series only to
its OWN history (a Shewhart individuals chart), and the k-of-5 + sustained-window
design already absorbs merge-volume correlation — so raw per-window counts/rates
are the correct individuals-chart observations and keep the capstone pure
counting (no git denominator, air-gap-trivially-correct).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import judge_independence as ji
from audit.metrics import disagreement_rate_ci
from audit.store import AuditSampleLedger
from erosion.trends import TrendStore, compute_monthly_trends
from escape.ledger import EscapeLedger
from escape.metrics import rolling_escape_count
from intervention.ledger import InterventionLedger
from intervention.metrics import rolling_correction_count
from vitals.models import (
    SERIES_AUDIT_DISAGREEMENT,
    SERIES_EROSION_DUPLICATION,
    SERIES_EROSION_SCATTER,
    SERIES_EROSION_SPREAD,
    SERIES_ESCAPES,
    SERIES_FAIL_OPEN,
    SERIES_INDEPENDENCE_UNAVAILABLE,
    SERIES_INTERVENTION_CORRECTIONS,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

_ESCAPE_LEDGER = "escape_ledger.jsonl"
_EROSION_TRENDS = "erosion_trends.jsonl"
_INTERVENTION_LEDGER = "intervention_ledger.jsonl"
_AUDIT_SAMPLES = "audit_samples.jsonl"


def _within_window(ts_str: str, now: datetime, days: int) -> bool:
    """Whether an ISO timestamp falls in ``[now - days, now]``. Tolerant of junk."""
    try:
        ts = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=now.tzinfo)
    return (now - timedelta(days=days)) <= ts <= now


def gather_series_readings(
    config: HydraFlowConfig, *, now: datetime, window_days: int
) -> dict[str, float | None]:
    """Compute the current per-window reading for every series.

    Returns a ``{series_name: reading | None}`` map. ``None`` marks an absent
    instrument (no ledger written yet); the loop skips those series so the
    verdict's coverage stays honest. Present-but-quiet series read ``0.0``.
    """
    diag = config.diagnostics_dir
    readings: dict[str, float | None] = {}

    # 1) Escapes — escapes detected within the trailing window (escape ledger).
    escape_path = diag / _ESCAPE_LEDGER
    if escape_path.exists():
        records = EscapeLedger(escape_path).read_latest()
        readings[SERIES_ESCAPES] = float(
            rolling_escape_count(records, now, days=window_days)
        )
    else:
        readings[SERIES_ESCAPES] = None

    # 2) Erosion — the latest monthly trend row's three surfaces.
    trends_path = diag / _EROSION_TRENDS
    rows = (
        compute_monthly_trends(TrendStore(trends_path).read_all())
        if trends_path.exists()
        else []
    )
    if rows:
        latest = rows[-1]
        readings[SERIES_EROSION_SPREAD] = float(latest.pct_crossing_3_modules)
        readings[SERIES_EROSION_SCATTER] = float(latest.scatter_findings)
        readings[SERIES_EROSION_DUPLICATION] = float(latest.duplication_density)
    else:
        readings[SERIES_EROSION_SPREAD] = None
        readings[SERIES_EROSION_SCATTER] = None
        readings[SERIES_EROSION_DUPLICATION] = None

    # 3) Intervention — CORRECTION-class touches in the window (approval excluded
    #    by construction of rolling_correction_count).
    iv_path = diag / _INTERVENTION_LEDGER
    if iv_path.exists():
        iv = InterventionLedger(iv_path).read_all()
        readings[SERIES_INTERVENTION_CORRECTIONS] = float(
            rolling_correction_count(iv, now, days=window_days)
        )
    else:
        readings[SERIES_INTERVENTION_CORRECTIONS] = None

    # 4) Audit — sampled re-audit disagreement rate over window-filtered samples.
    audit_path = diag / _AUDIT_SAMPLES
    if audit_path.exists():
        samples = AuditSampleLedger(audit_path).read_all()
        windowed = [
            s for s in samples if _within_window(s.audited_at, now, window_days)
        ]
        readings[SERIES_AUDIT_DISAGREEMENT] = float(disagreement_rate_ci(windowed).rate)
    else:
        readings[SERIES_AUDIT_DISAGREEMENT] = None

    # 5) Independence — fail-open + independence-unavailable events in the window,
    #    read via the owner's own windowed-count metric (one source of truth, the
    #    same import discipline the other four families use — never a divergent
    #    re-derivation of the window/kind filter here).
    ji_path = ji.ledger_path_for(config)
    if ji_path.exists():
        ji_records = ji.read_records(ji_path)
        readings[SERIES_FAIL_OPEN] = float(
            ji.rolling_kind_count(
                ji_records, now, days=window_days, kind=ji.KIND_FAIL_OPEN
            )
        )
        readings[SERIES_INDEPENDENCE_UNAVAILABLE] = float(
            ji.rolling_kind_count(
                ji_records,
                now,
                days=window_days,
                kind=ji.KIND_INDEPENDENCE_UNAVAILABLE,
            )
        )
    else:
        readings[SERIES_FAIL_OPEN] = None
        readings[SERIES_INDEPENDENCE_UNAVAILABLE] = None

    return readings


# --- primary-health precondition (the "green" gate) -------------------------


@dataclass(frozen=True)
class PrimaryHealth:
    """The first-order health reading that gates the whole monitor.

    ``ci_pass_rate`` and ``merge_throughput`` are the primary gates' own claim
    about the factory's health; this monitor speaks only when BOTH are within
    normal bands (green). Read from existing first-order signals — never a
    fusion or re-derivation of them (spec non-goal).
    """

    ci_pass_rate: float
    merge_throughput: int


def primary_health_green(
    health: PrimaryHealth, *, min_ci_pass_rate: float, min_merge_throughput: int
) -> bool:
    """Whether primary health sits within normal bands (the green precondition).

    Green requires the CI pass rate at/above its floor AND merge throughput
    at/above its floor: an idle or failing factory is not "green while dying",
    it is simply not green, and the monitor stays silent.
    """
    return (
        health.ci_pass_rate >= min_ci_pass_rate
        and health.merge_throughput >= min_merge_throughput
    )

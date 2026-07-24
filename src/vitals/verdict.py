"""The pure second-order vitals verdict engine (#10373).

Given the per-series observation histories (each a list of scalar per-window
readings, oldest → newest, the newest element being the current window), a
``primary_health_green`` precondition, and the anti-flap thresholds, this
computes the one vitals verdict — ``green | watch | diverging`` — plus the
full family/series breakdown that makes the verdict explainable from its inputs
on one page.

Decided divergence condition (spec FINAL):

* Each series carries its OWN Shewhart individuals-chart control limit,
  computed from a FROZEN baseline (the established history before the recent
  monitored windows) — Shewhart's phase-1/phase-2 split, so a step shift never
  re-absorbs into its own limit.
* A series is *sustained-breaching* when the last ``sustained_windows``
  observations ALL sit above that frozen UCL (a single high window never fires).
* A family (escapes / erosion / intervention / audit / independence) is
  *breaching* when ANY of its series is sustained-breaching, and *reporting*
  when ANY of its series has a primed baseline (≥ ``min_baseline_windows``).
* **watch** = primary green AND ``k ≥ watch_k`` breaching families.
* **diverging** = primary green AND ``k ≥ diverging_k`` breaching families.
* Primary health NOT green ⇒ ``green`` regardless of k: this monitor speaks
  only to divergence-while-green, never to ordinary red (existing first-order
  loops own that).

Counting FAMILIES (not raw series) is load-bearing: a single-dimension spike
inside one family is one vote, so erosion's three sub-series cannot manufacture
a three-family "diverging" on their own. Partial coverage is surfaced, never
silently treated as full — with families too young for a baseline the verdict
is ``green`` annotated ``n-of-5 reporting``.
"""

from __future__ import annotations

from vitals.control import breaches_upper, individuals_limits
from vitals.models import (
    FAMILY_SERIES,
    SERIES_LABELS,
    TOTAL_FAMILIES,
    FamilyDetail,
    SeriesDetail,
    VitalsThresholds,
    VitalsVerdict,
)

VERDICT_GREEN = "green"
VERDICT_WATCH = "watch"
VERDICT_DIVERGING = "diverging"


def _frozen_baseline(history: list[float], *, sustained_windows: int) -> list[float]:
    """The established baseline: everything before the monitored recent windows.

    Shewhart's phase-1/phase-2 split — the control limit is fixed from the
    established history and the recent ``sustained_windows`` observations are
    monitored against it. Freezing the baseline is what makes a *sustained* step
    shift detectable: a trailing baseline that re-absorbed the shift would raise
    its own limit and mask exactly the persistence this monitor is built to catch.
    """
    if sustained_windows <= 0:
        return list(history)
    return history[:-sustained_windows]


def _series_sustained_breach(
    history: list[float], *, min_baseline_windows: int, sustained_windows: int
) -> bool:
    """Whether the last ``sustained_windows`` observations all exceed the frozen UCL.

    Needs a primed baseline (``≥ min_baseline_windows`` established points, so a
    limit computed from one or two points is never trusted) AND every one of the
    recent windows above it. A single-window spike (only the newest point high)
    therefore never fires — that noise belongs to the owning instrument's finding
    path, not this monitor.
    """
    if len(history) < min_baseline_windows + max(1, sustained_windows):
        return False
    baseline = _frozen_baseline(history, sustained_windows=sustained_windows)
    if len(baseline) < max(1, min_baseline_windows):
        return False
    recent = history[-sustained_windows:]
    # SINGLE SOURCE OF TRUTH for the "above the 3σ upper control limit" decision:
    # every monitored window is tested through the very ``breaches_upper``
    # predicate the control chart owns, so the boundary — strictly above the
    # 3σ UCL, NOT merely above the baseline mean — lives in exactly one place.
    # ``all`` ⇒ EVERY one of the recent windows must breach (a single high
    # window never fires); the same ``min_baseline_windows`` floor is applied.
    return all(
        breaches_upper(v, baseline, min_windows=min_baseline_windows) for v in recent
    )


def _series_detail(
    name: str,
    history: list[float],
    *,
    min_baseline_windows: int,
    sustained_windows: int,
) -> SeriesDetail:
    """Build the legible per-series row: latest value vs its frozen control limit."""
    windows = len(history)
    value = history[-1] if history else 0.0
    baseline = _frozen_baseline(history, sustained_windows=sustained_windows)
    centre, ucl = individuals_limits(baseline)
    # A family is *reporting* only once its FROZEN baseline — the points the
    # control limit is actually computed from (history minus the monitored recent
    # windows) — is primed. Gating on the raw window count overstated readiness by
    # ``sustained_windows``: a limit derived from a baseline with fewer than
    # ``min_baseline_windows`` points is noise, not signal, and must not vote.
    reporting = len(baseline) >= max(1, min_baseline_windows)
    breaching = _series_sustained_breach(
        history,
        min_baseline_windows=min_baseline_windows,
        sustained_windows=sustained_windows,
    )
    return SeriesDetail(
        name=name,
        label=SERIES_LABELS.get(name, name),
        value=round(value, 4),
        center=round(centre, 4),
        ucl=round(ucl, 4),
        residual=round(value - ucl, 4),
        windows=windows,
        reporting=reporting,
        breaching=breaching,
    )


def evaluate_vitals(
    histories: dict[str, list[float]],
    *,
    primary_health_green: bool,
    thresholds: VitalsThresholds,
) -> VitalsVerdict:
    """Compute the vitals verdict from per-series histories + the primary gate.

    ``histories`` maps a series name to its full observation history (oldest →
    newest, newest = current window). Missing / empty series are treated as not
    reporting (honest degradation), never as a green vote of confidence.
    """
    family_details: list[FamilyDetail] = []
    breaching_families: list[str] = []
    reporting_families = 0

    for family, series_names in FAMILY_SERIES:
        series_details: list[SeriesDetail] = []
        family_reporting = False
        family_breaching = False
        for name in series_names:
            history = list(histories.get(name, []))
            detail = _series_detail(
                name,
                history,
                min_baseline_windows=thresholds.min_baseline_windows,
                sustained_windows=thresholds.sustained_windows,
            )
            series_details.append(detail)
            family_reporting = family_reporting or detail.reporting
            family_breaching = family_breaching or detail.breaching
        if family_reporting:
            reporting_families += 1
        # Only a REPORTING family can breach — a family with no primed baseline
        # cannot vote (its series' breach flags are False by construction, but
        # gate explicitly so intent is legible).
        family_breaching = family_breaching and family_reporting
        if family_breaching:
            breaching_families.append(family)
        family_details.append(
            FamilyDetail(
                family=family,
                reporting=family_reporting,
                breaching=family_breaching,
                series=tuple(series_details),
            )
        )

    k = len(breaching_families)
    verdict = _classify(
        k,
        primary_health_green=primary_health_green,
        watch_k=thresholds.watch_k,
        diverging_k=thresholds.diverging_k,
    )
    return VitalsVerdict(
        verdict=verdict,
        breaching_families=tuple(breaching_families),
        reporting_families=reporting_families,
        total_families=TOTAL_FAMILIES,
        primary_health_green=primary_health_green,
        families=tuple(family_details),
    )


def _classify(
    k: int, *, primary_health_green: bool, watch_k: int, diverging_k: int
) -> str:
    """Map the k-of-5 count + primary-health precondition to a verdict token."""
    if not primary_health_green:
        # The green-while-dying monitor is silent whenever the primary gates are
        # not themselves green — divergence FROM green is the entire signal.
        return VERDICT_GREEN
    if k >= diverging_k:
        return VERDICT_DIVERGING
    if k >= watch_k:
        return VERDICT_WATCH
    return VERDICT_GREEN

"""Render the vitals-methodology surface (ADR-0133 wiring, #10838).

ADR-0133 lands the fleet statistics — widened-limit multiplicity, published MDE,
time-between-events charts — as a pure engine (`vitals_methodology`). This surface
is that engine made *visible and maintained* on the real chart registry: the
falsifiability-baseline pattern (#11033), applied to the vitals fleet.

It answers, deterministically and per-PR: for the second-order vitals fleet as it
stands today (the series charted together in one verdict), what sigma multiplier
holds the family-wise false-alarm budget, is that above or still at the classic
3σ floor, and at what fleet size does widening begin to bite? Plus the published
MDE table and the scarce-event metrics that belong on a time-between-events chart.

It changes NO live threshold — the second-order vitals verdict still reads 3σ.
This surface is the readiness signal (and the registered-count-of-record) the
eventual live-limit migration needs; that migration is a deliberate behavior
change to live alarms and is out of scope of both this surface and ADR-0133.

Deterministic: a function of the static series registry (`vitals.models`) and the
pure ADR-0133 arithmetic alone — no model, no runtime data.
"""

from __future__ import annotations

from vitals.models import FAMILY_SERIES, SERIES_ESCAPES, SERIES_LABELS
from vitals_methodology import (
    CLASSIC_SHEWHART_SIGMA,
    DEFAULT_FAMILY_WISE_MONTHLY,
    mde_baseline_events,
    widened_sigma_multiplier,
)

_FOOTER = "\n\n{{ARCH_FOOTER}}\n"

#: Fleet sizes to project the widening curve over, so the reader sees where the
#: 3σ floor lifts (≈ n=19 at the 5% default) as the instrument fleet grows.
_PROJECTION_SIZES = (8, 15, 19, 30, 50, 70)

#: The rate ratios the published MDE table (ADR-0133 / #10838) reports.
_MDE_RATE_RATIOS = (2.0, 1.5, 1.25, 1.1, 0.9, 0.75, 0.5)


def _second_order_series() -> list[str]:
    """The series the second-order vitals verdict charts together (its fleet)."""
    return [name for _, series in FAMILY_SERIES for name in series]


def render_vitals_methodology(*, series_count: int | None = None) -> str:
    """Render the vitals-methodology readiness surface for the current fleet.

    *series_count* overrides the registered chart count (tests inject a fleet
    large enough to lift off the 3σ floor); by default it is read from the live
    second-order vitals series registry.
    """
    series = _second_order_series()
    n = series_count if series_count is not None else len(series)
    fw_pct = f"{DEFAULT_FAMILY_WISE_MONTHLY * 100:.0f}%"
    current_l = widened_sigma_multiplier(n)
    floored = current_l <= CLASSIC_SHEWHART_SIGMA

    out = "# Vitals Methodology (ADR-0133)\n\n"
    out += (
        "How the vitals instrument fleet is read *as evidence*: the widened-limit "
        "multiplier that holds the fleet's family-wise false-alarm budget, the "
        "minimum detectable effect per instrument, and which metrics belong on a "
        "time-between-events chart. Deterministic — a function of the registered "
        "series set and the ADR-0133 arithmetic alone. **No live threshold is "
        "changed by this surface**; it is the readiness signal for the eventual "
        "widened-limit migration.\n\n"
    )

    out += "## Widened control limit — the registered second-order fleet\n\n"
    out += (
        f"- **Registered series (charts evaluated together):** {n}\n"
        f"- **Family-wise budget:** {fw_pct} / month (Bonferroni, two-sided)\n"
        f"- **Widened multiplier L:** {current_l:.3f}σ "
        f"(classic Shewhart is {CLASSIC_SHEWHART_SIGMA:.1f}σ)\n"
    )
    if floored:
        out += (
            f"- **Status:** _at the 3σ floor_ — {n} charts at a {fw_pct} budget "
            f"computes a limit looser than 3σ, so the floor holds it at "
            f"{CLASSIC_SHEWHART_SIGMA:.1f}σ. The fleet does not need widening yet; "
            "the verdict's live 3σ limit is already correct.\n"
        )
    else:
        out += (
            f"- **Status:** _widened above 3σ_ — the fleet is large enough that "
            f"holding the {fw_pct} budget requires a limit wider than classic "
            "Shewhart. The live 3σ limit now over-alarms; this is the readiness "
            "signal for the widened-limit migration.\n"
        )

    out += "\n## Widening curve (readiness projection)\n\n"
    out += "Where the 3σ floor lifts as the instrument fleet grows:\n\n"
    out += "| Registered charts | Widened L | Above 3σ? |\n"
    out += "|------------------:|----------:|:---------:|\n"
    for size in _PROJECTION_SIZES:
        projected = widened_sigma_multiplier(size)
        above = "yes" if projected > CLASSIC_SHEWHART_SIGMA else "floored"
        marker = " ← current" if size == n else ""
        out += f"| {size}{marker} | {projected:.3f}σ | {above} |\n"

    out += "\n## Minimum detectable effect (per instrument, per window)\n\n"
    out += (
        "Baseline events a rate metric needs to detect a given rate ratio at "
        "α=0.05, 80% power. A metric whose window volume is below its row cannot "
        "evidence that effect — chart it as time-between-events instead of a rate.\n\n"
    )
    out += "| Rate ratio to detect | Baseline events needed |\n"
    out += "|---------------------:|-----------------------:|\n"
    for rr in _MDE_RATE_RATIOS:
        out += f"| {rr:g}× | {mde_baseline_events(rr):.0f} |\n"

    out += "\n## Scarce-event metrics (time-between-events candidates)\n\n"
    out += (
        "A per-window count that is usually zero (escapes on a low-merge repo) has "
        "no power as a rate chart — a monthly 'flat' reading on ~1.5 events/month "
        "is not evidence. These move to a Benneyan g/t-chart on the interval "
        "between events:\n\n"
    )
    escapes_label = SERIES_LABELS.get(SERIES_ESCAPES, SERIES_ESCAPES)
    out += (
        f"- **{escapes_label}** (`{SERIES_ESCAPES}`) — escapes are rare by design; "
        "a g-chart on merges-between-escapes (+ the consecutive-zeros run rule) "
        "reads deterioration a rate chart's 0-pinned lower limit cannot.\n"
    )

    return out + _FOOTER

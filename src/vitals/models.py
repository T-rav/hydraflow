"""Family / series taxonomy + verdict value objects for second-order vitals (#10373).

The capstone falsification instrument watches FIVE input families for
*correlated adverse drift while the primary gates stay green* — the
green-while-dying condition no single second-order series can see. Each family
reduces to one or more scalar per-window series; a family is "above its control
limit" when ANY of its series breaches its own Shewhart individuals-chart UCL,
sustained across consecutive windows. This module is the pure taxonomy + the
value objects the verdict engine and report renderer share (no IO, no logic
beyond the fixed mapping).

The five families (spec ``docs/proposals/second-order-vitals.md``, FINAL):

1. ``escapes``       — escapes per window (escape ledger)
2. ``erosion``       — change-spread, concept-scatter, duplication density
3. ``intervention``  — correction-class intervention rate (approval EXCLUDED)
4. ``audit``         — sampled re-audit disagreement rate
5. ``independence``  — fail-open + independence-unavailable rates

Erosion carries three sub-series but counts as ONE family; independence carries
two. The k-of-5 divergence condition counts FAMILIES, never raw series, so a
single-dimension spike inside one family is not five votes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- series identities (the 7 scalar per-window observations) ---------------

SERIES_ESCAPES = "escapes"
SERIES_EROSION_SPREAD = "erosion_spread"
SERIES_EROSION_SCATTER = "erosion_scatter"
SERIES_EROSION_DUPLICATION = "erosion_duplication"
SERIES_INTERVENTION_CORRECTIONS = "intervention_corrections"
SERIES_AUDIT_DISAGREEMENT = "audit_disagreement"
SERIES_FAIL_OPEN = "fail_open"
SERIES_INDEPENDENCE_UNAVAILABLE = "independence_unavailable"

# --- family identities (the 5 votes) ----------------------------------------

FAMILY_ESCAPES = "escapes"
FAMILY_EROSION = "erosion"
FAMILY_INTERVENTION = "intervention"
FAMILY_AUDIT = "audit"
FAMILY_INDEPENDENCE = "independence"

#: Ordered family → its constituent scalar series. Ordered so the report and
#: the persisted verdict render deterministically (same inputs → same page).
FAMILY_SERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FAMILY_ESCAPES, (SERIES_ESCAPES,)),
    (
        FAMILY_EROSION,
        (
            SERIES_EROSION_SPREAD,
            SERIES_EROSION_SCATTER,
            SERIES_EROSION_DUPLICATION,
        ),
    ),
    (FAMILY_INTERVENTION, (SERIES_INTERVENTION_CORRECTIONS,)),
    (FAMILY_AUDIT, (SERIES_AUDIT_DISAGREEMENT,)),
    (
        FAMILY_INDEPENDENCE,
        (SERIES_FAIL_OPEN, SERIES_INDEPENDENCE_UNAVAILABLE),
    ),
)

#: Total number of input families (the 5 in ``k-of-5``). Derived, not a magic 5.
TOTAL_FAMILIES = len(FAMILY_SERIES)

# Human-readable series labels for the generated report / dashboard payload.
SERIES_LABELS: dict[str, str] = {
    SERIES_ESCAPES: "escapes per window",
    SERIES_EROSION_SPREAD: "% changes crossing ≥3 modules",
    SERIES_EROSION_SCATTER: "scatter findings",
    SERIES_EROSION_DUPLICATION: "duplication density",
    SERIES_INTERVENTION_CORRECTIONS: "correction-class interventions per window",
    SERIES_AUDIT_DISAGREEMENT: "re-audit disagreement rate",
    SERIES_FAIL_OPEN: "fail-open events per window",
    SERIES_INDEPENDENCE_UNAVAILABLE: "independence-unavailable events per window",
}


# --- verdict thresholds (configurable knobs, passed in from config) ---------


@dataclass(frozen=True)
class VitalsThresholds:
    """The anti-flap knobs the verdict engine evaluates against.

    ``min_baseline_windows`` — a series carries no control limit (and its family
    does not count as *reporting*) until it has accumulated at least this many
    observations; the spec's "primed from the series' own history once ≥1 full
    window exists", made concrete as a floor on the individuals-chart baseline.
    ``sustained_windows`` — how many CONSECUTIVE windows a family must stay above
    its limit before it counts (single-window blips are not divergence).
    ``watch_k`` / ``diverging_k`` — the k-of-5 family thresholds.
    """

    min_baseline_windows: int = 8
    sustained_windows: int = 2
    watch_k: int = 2
    diverging_k: int = 3


# --- verdict value objects (pure; shared by engine + report + endpoint) -----


@dataclass(frozen=True)
class SeriesDetail:
    """One series' latest reading against its own control limit (for legibility)."""

    name: str
    label: str
    value: float
    center: float
    ucl: float
    residual: float  # value - ucl (positive == above the limit)
    windows: int  # how many observations the series has accumulated
    reporting: bool  # baseline primed (windows >= min_baseline_windows)
    breaching: bool  # sustained above the limit


@dataclass(frozen=True)
class FamilyDetail:
    """One family's roll-up: reporting + sustained-breach + its series."""

    family: str
    reporting: bool
    breaching: bool
    series: tuple[SeriesDetail, ...] = ()


@dataclass(frozen=True)
class VitalsVerdict:
    """The one vitals verdict, fully explainable from its ``families`` on one page.

    ``verdict`` is ``green | watch | diverging``. ``reporting_families`` /
    ``total_families`` express partial coverage honestly ("n-of-5 reporting").
    ``breaching_families`` is the k that drove the verdict. ``primary_health_green``
    records the precondition: watch/diverging can only be reached while primary
    health is green (the green-while-dying framing).
    """

    verdict: str
    breaching_families: tuple[str, ...]
    reporting_families: int
    total_families: int
    primary_health_green: bool
    families: tuple[FamilyDetail, ...] = field(default_factory=tuple)

    @property
    def k(self) -> int:
        """Number of families sustained above their control limits."""
        return len(self.breaching_families)

    @property
    def coverage_label(self) -> str:
        """The honest partial-coverage annotation shown on every verdict."""
        return f"{self.reporting_families}-of-{self.total_families} reporting"

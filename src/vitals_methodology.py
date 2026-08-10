"""Vitals methodology: the statistics that make the instrument fleet mean something.

Load-bearing decision-of-record: **ADR-0133**. This module is the executable
half of that ADR — the arithmetic behind the four rulings that govern how every
vitals instrument (finder calibration #10821, judge independence #10836,
assertion density #10917, escape/erosion ledgers, second-order vitals) is read
*as evidence*. Pure functions over floats/ints; no IO, no ML, no config — the
callers own cadence and registration, this module owns the maths.

The four pillars (see ADR-0133):

1. **Multiplicity = widened limits** (RULED, author 2026-07-29). Classical SPC
   does not treat charts as hypothesis tests; it designs by average run length.
   A fleet of ``n`` individuals-charts each at a naive 3-sigma limit alarms
   ``n``× too often. The Shewhart-native fix (Mortell & Runger 1995; Epprecht
   2011) is to *widen* every chart's limit so the whole fleet alarms as rarely
   as the design intends. The widening factor derives ONLY from the registered
   instrument count — never a tick cadence, never a hardcode — so it stays
   honest as the fleet grows. Alarms are decided at CYCLE granularity: a chart's
   state is evaluated once per review cycle, so intermediate polls update data
   but cannot fire, and the widening arithmetic depends on chart count alone.

2. **Alarm philosophy + triage budget** (ISA-18.2 discipline, *not* statistical
   false-alarm control). Every alarm must be *rationalized*: a documented
   operator response, a priority, and a consequence of inaction — or it is
   removed. A review cycle carries a bounded triage budget.

3. **Minimum detectable effect (MDE).** Publish, per instrument per window, the
   baseline event count needed to detect the rate ratio the instrument claims to
   monitor — and refuse to chart a metric whose MDE it cannot meet. A monthly
   "escapes are flat" claim on 1.5 events/month is not evidence.

4. **Time-between-events charts for scarce events.** Where events are too rare
   for a rate chart, switch to a g/t-chart on the interval between events, with
   the Benneyan consecutive-zeros run rule so deterioration shows even though the
   lower limit is pinned at zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import NormalDist

__all__ = [
    "DEFAULT_FAMILY_WISE_MONTHLY",
    "CLASSIC_SHEWHART_SIGMA",
    "MultiplicityMethod",
    "widened_sigma_multiplier",
    "mde_baseline_events",
    "can_chart",
    "TBEChartLimits",
    "time_between_events_limits",
    "consecutive_zeros_run_limit",
    "AlarmPriority",
    "TRIAGE_BUDGET_PER_CYCLE",
    "AlarmDefinition",
    "RationalizationReport",
    "rationalize",
]

#: The classic Shewhart constant. An in-control individuals chart exceeds
#: ``mean + 3·sigma`` only ~0.13% of the time (one-sided). Every naive vitals
#: chart in the fleet assumes this; widening replaces it fleet-aware.
CLASSIC_SHEWHART_SIGMA = 3.0

#: Default family-wise false-alarm probability for the whole fleet, per review
#: month. 5% is the ticket's worked target ("70 charts at 5% monthly → ~3.4σ").
DEFAULT_FAMILY_WISE_MONTHLY = 0.05

#: A unit normal, reused for probit (inverse-CDF) lookups.
_UNIT_NORMAL = NormalDist(0.0, 1.0)


class MultiplicityMethod(StrEnum):
    """How a family-wise budget is split across the registered instruments.

    ``BONFERRONI`` — per-chart α = family_wise / n. Simple, slightly
    conservative, and the arithmetic the ADR's headline number quotes.
    ``SIDAK`` — per-chart α = 1 − (1 − family_wise)^(1/n). Exact under
    independence; marginally tighter limits than Bonferroni.
    """

    BONFERRONI = "bonferroni"
    SIDAK = "sidak"


# --- Pillar 1: widened control limits ---------------------------------------


def _per_chart_alpha(
    n_instruments: int, family_wise: float, method: MultiplicityMethod
) -> float:
    """Split a family-wise false-alarm budget across ``n_instruments`` charts."""
    if method is MultiplicityMethod.SIDAK:
        return 1.0 - (1.0 - family_wise) ** (1.0 / n_instruments)
    return family_wise / n_instruments


def widened_sigma_multiplier(
    n_instruments: int,
    *,
    family_wise_monthly: float = DEFAULT_FAMILY_WISE_MONTHLY,
    two_sided: bool = True,
    method: MultiplicityMethod = MultiplicityMethod.BONFERRONI,
) -> float:
    """The sigma multiplier ``L`` for each chart so the *fleet* holds its budget.

    Replaces the hardcoded ``3.0`` in an individuals chart's ``mean + L·sigma``
    limit with a value that grows with the registered instrument count, so the
    whole fleet's monthly false-alarm probability stays at *family_wise_monthly*
    rather than ``n`` times the single-chart rate.

    ``n_instruments`` is the count of REGISTERED instruments (charts), never a
    tick/evaluation count — alarms are decided at cycle granularity (ADR-0133),
    so polling cadence never enters the arithmetic. ``two_sided`` controls
    whether the budget is split across both tails (the default, matching the
    ADR's ~3.4σ-at-70-charts headline) or the upper tail only (for the fleet's
    upper-control-limit-only charts).

    Worked anchors from #10838 (two_sided=True, Bonferroni, 5% monthly):
    ``n=1 → 3.0`` (the raw 1.96σ is floored), ``n=70 → ~3.4``. And the group-chart result
    (upper-tail budget = a single 3σ one-sided chart) recovers Mortell &
    Runger's ``n=10 → 3.64`` when called with the matching arguments.

    The result is **floored at the classic 3.0**: we only ever WIDEN. A small
    fleet under a loose monthly budget would compute a limit tighter than 3σ
    (a single chart at 5% is just 1.96σ), but the existing charts assume 3σ and
    tightening them would over-alarm — so the floor keeps the fleet at classic
    Shewhart until it is large enough to genuinely need wider limits (n ≳ 19 at
    the 5% default). ``n_instruments <= 0`` is meaningless (no fleet); returns
    the classic 3.0 rather than dividing by zero.
    """
    if n_instruments <= 0:
        return CLASSIC_SHEWHART_SIGMA
    alpha_chart = _per_chart_alpha(n_instruments, family_wise_monthly, method)
    # Guard the probit against an exhausted or degenerate budget.
    alpha_chart = min(max(alpha_chart, 1e-12), 1.0 - 1e-12)
    tail = alpha_chart / 2.0 if two_sided else alpha_chart
    return max(CLASSIC_SHEWHART_SIGMA, _UNIT_NORMAL.inv_cdf(1.0 - tail))


# --- Pillar 3: minimum detectable effect ------------------------------------


def mde_baseline_events(
    rate_ratio: float,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Baseline events per window needed to detect *rate_ratio* at *alpha*/*power*.

    Variance-stabilised (square-root transform) Poisson power: for a rate metric
    with expected baseline count μ₀ per window, detecting a rate ratio ``RR`` at
    two-sided significance *alpha* with *power* needs approximately

        μ₀ ≈ (z_{α/2} + z_power)² / (4 · (√RR − 1)²)

    which at α=0.05, power=0.80 collapses to the ticket's ``≈ 1.96/(√RR − 1)²``
    and reproduces its published table (RR=2 → 11, 1.5 → 39, 1.25 → 141,
    1.1 → 824, 0.5 → 23, 0.75 → 109, 0.9 → 745). Return is a float event count;
    callers round up. ``RR == 1`` (no effect to detect) needs infinite data →
    ``math.inf``.
    """
    if rate_ratio <= 0.0:
        raise ValueError(f"rate_ratio must be positive, got {rate_ratio!r}")
    if rate_ratio == 1.0:
        return math.inf
    z_alpha = _UNIT_NORMAL.inv_cdf(1.0 - alpha / 2.0)
    z_power = _UNIT_NORMAL.inv_cdf(power)
    root_gap = math.sqrt(rate_ratio) - 1.0
    return (z_alpha + z_power) ** 2 / (4.0 * root_gap * root_gap)


def can_chart(
    baseline_events: float,
    rate_ratio: float,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> bool:
    """Whether a rate chart has the power to detect the effect it claims to watch.

    True iff the instrument's *baseline_events* per window meets or exceeds the
    MDE for *rate_ratio*. A metric that cannot — a low-volume loop asked to catch
    a doubling on 1.5 events/month — must not be charted as a rate; move it to a
    time-between-events chart (see :func:`time_between_events_limits`) instead.
    """
    return baseline_events >= mde_baseline_events(rate_ratio, alpha=alpha, power=power)


# --- Pillar 4: time-between-events (g/t) charts ------------------------------


@dataclass(frozen=True, slots=True)
class TBEChartLimits:
    """Control limits for a chart of the interval between rare events.

    ``centre`` is the *geometric* median (0.693 × mean), not the mean, because
    the between-events distribution is badly right-skewed. ``lower`` is pinned at
    0 — an interval cannot be negative — which is why deterioration (intervals
    shrinking toward 0) needs the consecutive-zeros run rule to be visible.
    """

    centre: float
    upper: float
    lower: float


#: Benneyan's geometric-median factor for the g/t-chart centreline.
_GEOMETRIC_MEDIAN_FACTOR = 0.693


def time_between_events_limits(mean_interval: float) -> TBEChartLimits:
    """g/t-chart limits for a mean interval between events (Benneyan 2001).

        centre = 0.693 × mean
        UCL    = mean + 3·√(mean² + mean)
        LCL    = max(0, mean − 3·√(mean² + mean))

    *mean_interval* is the mean count of opportunities (merges, days, …) between
    two occurrences, from 20–40 baseline subgroups. ``mean_interval <= 0`` has no
    chart; returns all-zero limits.
    """
    if mean_interval <= 0.0:
        return TBEChartLimits(centre=0.0, upper=0.0, lower=0.0)
    spread = 3.0 * math.sqrt(mean_interval * mean_interval + mean_interval)
    return TBEChartLimits(
        centre=_GEOMETRIC_MEDIAN_FACTOR * mean_interval,
        upper=mean_interval + spread,
        lower=max(0.0, mean_interval - spread),
    )


def consecutive_zeros_run_limit(mean_interval: float, *, alpha: float = 0.05) -> int:
    """Smallest run of zero-interval events that is improbable in control.

    A g-chart's LCL sits at 0, so a rate *increase* (events bunching, intervals
    collapsing to 0) cannot breach a limit — it can only show as an improbable
    *run*. For a geometric process with mean interval ``m``, the probability an
    interval is 0 is ``p0 = 1/(m + 1)``; ``k`` consecutive zeros has probability
    ``p0^k``. Return the smallest ``k`` with ``p0^k <= alpha`` — the run length
    the Benneyan rule should alarm on. ``mean_interval <= 0`` → 1 (any event is
    already anomalous).
    """
    if mean_interval <= 0.0:
        return 1
    p_zero = 1.0 / (mean_interval + 1.0)
    if p_zero <= 0.0:
        return 1
    # smallest k with p_zero**k <= alpha  ->  k >= log(alpha)/log(p_zero)
    return max(1, math.ceil(math.log(alpha) / math.log(p_zero)))


# --- Pillar 2: alarm philosophy + triage budget (ISA-18.2 discipline) -------


class AlarmPriority(StrEnum):
    """Alarm priority. ISA-18.2 guidance targets a ~80/15/5 LOW/MEDIUM/HIGH split."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


#: ISA-18.2 acceptable steady-state alarm rate: ~6 alarms/hour/operating
#: position. A review cycle's triage budget is a human-cognition constraint, not
#: a statistical one — an alarm over budget is a rationalization failure, not a
#: false positive. Kept here as the single source the review cycle reads.
TRIAGE_BUDGET_PER_CYCLE = 6


@dataclass(frozen=True, slots=True)
class AlarmDefinition:
    """One instrument's alarm, rationalized per ISA-18.2.

    An alarm exists only if a human can act on it: it must name the *operator
    response*, a *priority*, and the *consequence of inaction*. An alarm missing
    any of these is not a low-priority alarm — it is not an alarm, and
    :func:`rationalize` marks it for removal.
    """

    instrument_id: str
    documented_response: str
    priority: AlarmPriority
    consequence_of_inaction: str

    @property
    def is_rationalized(self) -> bool:
        """True iff every required field carries real (non-blank) content."""
        return bool(
            self.instrument_id.strip()
            and self.documented_response.strip()
            and self.consequence_of_inaction.strip()
        )


@dataclass(frozen=True, slots=True)
class RationalizationReport:
    """The outcome of rationalizing a fleet's alarms against ISA-18.2 discipline."""

    rationalized: tuple[AlarmDefinition, ...]
    to_remove: tuple[AlarmDefinition, ...]
    priority_counts: dict[AlarmPriority, int]

    @property
    def over_triage_budget(self) -> bool:
        """True when the rationalized alarm count exceeds the per-cycle budget."""
        return len(self.rationalized) > TRIAGE_BUDGET_PER_CYCLE


def rationalize(alarms: list[AlarmDefinition]) -> RationalizationReport:
    """Partition *alarms* into keep/remove and tally the priority split.

    Rationalized alarms are those whose required fields are all present; the rest
    are marked for removal (an un-actionable alarm is noise). The priority counts
    are computed over the rationalized set only — the split you would present to
    an operator, checkable against the ISA-18.2 ~80/15/5 target.
    """
    rationalized = tuple(a for a in alarms if a.is_rationalized)
    to_remove = tuple(a for a in alarms if not a.is_rationalized)
    counts: dict[AlarmPriority, int] = dict.fromkeys(AlarmPriority, 0)
    for alarm in rationalized:
        counts[alarm.priority] += 1
    return RationalizationReport(
        rationalized=rationalized,
        to_remove=to_remove,
        priority_counts=counts,
    )

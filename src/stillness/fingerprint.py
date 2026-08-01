"""Oscillation fingerprint (#10820) — pure computation + report rendering.

A read-only diagnostic that ranks the loops/paths carrying the most factory
"flux" (self-generated churn) over a trailing window, so the setpoint-conversion
work (#10824) damps the right loops. This module is **pure**: it computes over
typed inputs (issue/merge/loop records the caller fetches from ``gh``/``git``/the
loop registry) and renders a Markdown report. It never fetches, never writes, and
— per the issue — never files an issue ("a diagnostic that adds intake would be
self-parody").

Five series, all from existing telemetry (see #10820):

1. **Self-sourced fraction** — share of opened work whose origin is a loop/finder
   vs external/human, per week. Rising fraction + rising flux == hunting.
2. **Rework ratio** — share of merges touching a file merged within the prior 14
   days (the direct wake-reading measure).
3. **Verdict flapping** — per-stage counts from ``ConvergenceOscillationLoop``'s
   escalation issues (consumed, never recomputed). Zero in-window is itself a
   finding: the flux is fleet-level, not per-item.
4. **Flat finders** — finder labels whose open-rate stayed flat while the backlog
   burned down. Noise-floor suspects.
5. **Saturation markers** — cost-budget cap events, the boundary markers for
   post-saturation windup bursts.

Origin is classified by **label**, not author: the factory files under a human
token, so author is not a reliable origin signal (a ``hydraflow-find`` issue may
be authored by the operator). This is a documented proxy.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

# Labels a loop applies when it files work. `hydraflow-find` is the canonical
# "a loop opened this" marker; the co-labels name the specific finder.
FINDER_LABEL = "hydraflow-find"
HITL_ESCALATION_LABEL = "hydraflow-hitl-escalation"
OSCILLATION_LABEL = "convergence-oscillation"
# Co-labels that pin a finder to a specific loop (the only clean loop↔issue key).
_FINDER_COLABELS = {
    "sampled-audit",
    "cost-budget",
    "cost-budget-exceeded",
    "issue-cost-spike",
    "issue-cost",
    OSCILLATION_LABEL,
    "audit-upheld",
    "staging-rc-dryrun",
}
# Pipeline-entry labels a human applies to route real work.
_PIPELINE_LABELS = {"hydraflow-plan", "hydraflow-diagnose"}


class Origin(StrEnum):
    """How a work item entered the system."""

    SELF = "self"  # a loop/finder filed it (hydraflow-find / escalation)
    PIPELINE = "pipeline"  # human routed real work (plan/diagnose)
    EXTERNAL = "external"  # neither — an outside/human-opened item


@dataclass(frozen=True)
class IssueRecord:
    number: int
    created_at: datetime
    labels: tuple[str, ...]
    author: str
    closed_at: datetime | None = None


@dataclass(frozen=True)
class MergeRecord:
    sha: str
    merged_at: datetime
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class LoopInfo:
    name: str
    module: str
    tick_seconds: int | None


# ---------------------------------------------------------------------------
# Origin classification (label-based, documented proxy)
# ---------------------------------------------------------------------------


def classify_origin(labels: tuple[str, ...]) -> Origin:
    labset = set(labels)
    if FINDER_LABEL in labset or HITL_ESCALATION_LABEL in labset:
        return Origin.SELF
    if labset & _PIPELINE_LABELS:
        return Origin.PIPELINE
    return Origin.EXTERNAL


def finder_key(labels: tuple[str, ...]) -> str:
    """The finder a self-sourced issue is attributable to.

    Returns the most specific co-label if present, else ``hydraflow-find``
    (generic — not attributable to a single loop, per the map's foreign-key gap).
    """
    for co in sorted(set(labels) & _FINDER_COLABELS):
        return co
    return FINDER_LABEL


# ---------------------------------------------------------------------------
# Series 1 — self-sourced fraction (weekly trend)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekPoint:
    week_start: datetime
    self_count: int
    pipeline_count: int
    external_count: int

    @property
    def total(self) -> int:
        return self.self_count + self.pipeline_count + self.external_count

    @property
    def self_fraction(self) -> float:
        return self.self_count / self.total if self.total else 0.0


def _week_start(dt: datetime, origin: datetime) -> datetime:
    """Bucket `dt` into a week index anchored at `origin` (Monday-agnostic:
    weeks are counted back from the window start so the last bucket is 'now')."""
    weeks = (dt - origin).days // 7
    return origin + timedelta(weeks=weeks)


def weekly_self_sourced_fraction(
    issues: list[IssueRecord], *, now: datetime, weeks: int
) -> list[WeekPoint]:
    window_start = now - timedelta(weeks=weeks)
    buckets: dict[datetime, list[Origin]] = {}
    for iss in issues:
        if iss.created_at < window_start or iss.created_at > now:
            continue
        wk = _week_start(iss.created_at, window_start)
        buckets.setdefault(wk, []).append(classify_origin(iss.labels))
    points: list[WeekPoint] = []
    for wk in sorted(buckets):
        origins = buckets[wk]
        c = Counter(origins)
        points.append(
            WeekPoint(
                week_start=wk,
                self_count=c[Origin.SELF],
                pipeline_count=c[Origin.PIPELINE],
                external_count=c[Origin.EXTERNAL],
            )
        )
    return points


def trend_slope(points: list[WeekPoint]) -> float:
    """Least-squares slope of self_fraction over week index (fraction/week)."""
    n = len(points)
    if n < 2:
        return 0.0
    xs = list(range(n))
    ys = [p.self_fraction for p in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


# ---------------------------------------------------------------------------
# Series 2 — rework ratio (wake-reading)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReworkResult:
    total_merges: int
    reworked_merges: int
    hot_paths: list[tuple[str, int]]  # (path, times it appeared in a rework merge)

    @property
    def ratio(self) -> float:
        return self.reworked_merges / self.total_merges if self.total_merges else 0.0


# Deterministic regen artifacts: every PR rewrites them, so counting them as
# "rework" measures the regen machinery, not genuine wake-reading. Excluded by
# default (the first real run showed changelog.md/.meta.json dominating the
# hot-paths — a false signal).
_GENERATED_PREFIXES = (
    "docs/arch/generated/",
    "docs/arch/.meta.json",
    "docs/arch/generated/ubiquitous-language.md",
)


def is_generated_artifact(path: str) -> bool:
    return any(path.startswith(p) or path == p for p in _GENERATED_PREFIXES)


def rework_ratio(
    merges: list[MergeRecord],
    *,
    now: datetime,
    weeks: int,
    window_days: int = 14,
    ignore_generated: bool = True,
) -> ReworkResult:
    window_start = now - timedelta(weeks=weeks)

    def _paths(m: MergeRecord) -> set[str]:
        if not ignore_generated:
            return set(m.changed_paths)
        return {p for p in m.changed_paths if not is_generated_artifact(p)}

    # Two roles: *report* merges (inside [window_start, now]) are the numerator +
    # denominator; ALL supplied merges (which the caller fetches with an extra
    # window_days lookback buffer) are the prior-overlap lookup pool — so a merge
    # in the first 14d of the report window can still see a genuine prior merge
    # that landed just BEFORE window_start (else the earliest ~window_days are
    # structurally undercounted).
    all_sorted = sorted(merges, key=lambda m: m.merged_at)
    report_merges = [m for m in all_sorted if window_start <= m.merged_at <= now]
    reworked = 0
    hot: Counter[str] = Counter()
    for m in report_merges:
        prior_cutoff = m.merged_at - timedelta(days=window_days)
        prior_paths: set[str] = set()
        for earlier in all_sorted:
            if earlier.merged_at >= m.merged_at:
                break
            if earlier.merged_at >= prior_cutoff:
                prior_paths.update(_paths(earlier))
        overlap = _paths(m) & prior_paths
        if overlap:
            reworked += 1
            hot.update(overlap)
    return ReworkResult(
        total_merges=len(report_merges),
        reworked_merges=reworked,
        hot_paths=hot.most_common(10),
    )


# ---------------------------------------------------------------------------
# Series 3 — verdict flapping (consume ConvergenceOscillationLoop)
# ---------------------------------------------------------------------------

_STAGES_RE = re.compile(r"Oscillating boundary stages:\**\s*(.+)", re.IGNORECASE)


@dataclass(frozen=True)
class FlappingResult:
    total_escalations: int
    per_stage: list[tuple[str, int]]
    fired_in_probe_window: bool  # 2026-07-14 .. 07-28, the quiet-fortnight check

    @property
    def is_fleet_level_evidence(self) -> bool:
        """Zero per-item escalations while flux grew ⇒ oscillation was fleet-level."""
        return self.total_escalations == 0


def _parse_stages(body: str) -> list[str]:
    # ConvergenceOscillationLoop renders stages backtick-wrapped, e.g.
    # "Oscillating boundary stages: `plan`, `triage`" — strip the backticks so
    # the keys are the bare stage names (triage/plan), not "`plan`".
    m = _STAGES_RE.search(body or "")
    if not m:
        return []
    raw = m.group(1).splitlines()[0]
    return [
        s.strip().strip("`") for s in re.split(r"[,/]", raw) if s.strip().strip("`")
    ]


def verdict_flapping(
    escalations: list[IssueRecord],
    bodies: dict[int, str],
    *,
    probe_start: datetime,
    probe_end: datetime,
) -> FlappingResult:
    stage_counts: Counter[str] = Counter()
    fired = False
    for iss in escalations:
        if probe_start <= iss.created_at <= probe_end:
            fired = True
        for stage in _parse_stages(bodies.get(iss.number, "")):
            stage_counts[stage] += 1
    return FlappingResult(
        total_escalations=len(escalations),
        per_stage=stage_counts.most_common(),
        fired_in_probe_window=fired,
    )


# ---------------------------------------------------------------------------
# Series 4 — flat finders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinderSeries:
    finder: str
    weekly_counts: list[int]

    @property
    def total(self) -> int:
        return sum(self.weekly_counts)

    @property
    def is_flat(self) -> bool:
        """Non-trivial, low-variance output — a noise-floor suspect."""
        active = list(self.weekly_counts)
        if sum(active) < len(active):  # averages <1/week — not a carrier
            return False
        mean = sum(active) / len(active)
        if mean == 0:
            return False
        variance = sum((c - mean) ** 2 for c in active) / len(active)
        # coefficient of variation < 0.5 ⇒ steady output regardless of demand
        return (variance**0.5) / mean < 0.5


def finder_activity(
    issues: list[IssueRecord], *, now: datetime, weeks: int
) -> list[FinderSeries]:
    window_start = now - timedelta(weeks=weeks)
    per_finder: dict[str, list[int]] = {}
    for iss in issues:
        if iss.created_at < window_start or iss.created_at > now:
            continue
        if classify_origin(iss.labels) is not Origin.SELF:
            continue
        wk = (iss.created_at - window_start).days // 7
        if not 0 <= wk < weeks:
            continue
        key = finder_key(iss.labels)
        per_finder.setdefault(key, [0] * weeks)[wk] += 1
    return sorted(
        (FinderSeries(finder=k, weekly_counts=v) for k, v in per_finder.items()),
        key=lambda s: s.total,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Series 5 — saturation markers
# ---------------------------------------------------------------------------

_SATURATION_LABELS = {"cost-budget", "cost-budget-exceeded", "issue-cost-spike"}


def saturation_markers(issues: list[IssueRecord]) -> list[datetime]:
    return sorted(
        iss.created_at for iss in issues if set(iss.labels) & _SATURATION_LABELS
    )


# ---------------------------------------------------------------------------
# Classification tags — tick vs window
# ---------------------------------------------------------------------------

# A loop whose tick is much faster than the span its output describes over-samples
# a slow signal — the damper-0a (#10843) candidates. We flag sub-hourly ticks;
# the true per-loop measurement window is a manual classification the report notes.
_FAST_TICK_SECONDS = 3600


def fast_tick_loops(loops: list[LoopInfo]) -> list[LoopInfo]:
    return sorted(
        (
            lp
            for lp in loops
            if lp.tick_seconds is not None and lp.tick_seconds < _FAST_TICK_SECONDS
        ),
        key=lambda lp: lp.tick_seconds or 0,
    )


# ---------------------------------------------------------------------------
# Ranking — the deliverable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FluxCarrier:
    finder: str
    self_issues: int
    share_of_self: float
    is_flat: bool
    loop: LoopInfo | None


def rank_flux_carriers(
    finders: list[FinderSeries],
    flapping: FlappingResult,
    loops_by_finder: dict[str, LoopInfo],
    *,
    top_n: int = 3,
) -> list[FluxCarrier]:
    # `flapping` is accepted for signature stability but no longer used to tag
    # carriers: oscillation escalations are keyed by pipeline STAGE (triage/plan),
    # a different domain from finder/loop identity (sampled-audit, cost-budget),
    # so there is no sound join — the old "appears_in_oscillation" column was
    # structurally always false. The fleet-level escalation count is reported in
    # its own series instead.
    total_self = sum(f.total for f in finders) or 1
    carriers = [
        FluxCarrier(
            finder=f.finder,
            self_issues=f.total,
            share_of_self=f.total / total_self,
            is_flat=f.is_flat,
            loop=loops_by_finder.get(f.finder),
        )
        for f in finders
    ]
    return carriers[:top_n]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class Fingerprint:
    generated_at: datetime
    weeks: int
    self_series: list[WeekPoint]
    rework: ReworkResult
    flapping: FlappingResult
    finders: list[FinderSeries]
    saturation: list[datetime]
    fast_ticks: list[LoopInfo]
    carriers: list[FluxCarrier]
    gaps: list[str] = field(default_factory=list)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_report(fp: Fingerprint) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Oscillation Fingerprint (#10820)")
    a("")
    a(
        f"Read-only diagnostic — generated {fp.generated_at:%Y-%m-%d} over the "
        f"trailing **{fp.weeks} weeks**. Ranks the loops/paths carrying the most "
        "self-generated flux, so setpoint conversion (#10824) damps the right "
        "loops. Files nothing; remediates nothing."
    )
    a("")
    a("## Top flux carriers")
    a("")
    if fp.carriers:
        a("| # | Finder | Self issues | Share | Flat? | Loop tick |")
        a("|---|---|---|---|---|---|")
        for i, c in enumerate(fp.carriers, 1):
            tick = f"{c.loop.tick_seconds}s" if c.loop and c.loop.tick_seconds else "—"
            a(
                f"| {i} | `{c.finder}` | {c.self_issues} | {_pct(c.share_of_self)} "
                f"| {'yes' if c.is_flat else 'no'} | {tick} |"
            )
    else:
        a("_No self-sourced work in the window — nothing to rank._")
    a("")
    a("## Series")
    a("")
    a("### 1. Self-sourced fraction (weekly) — LOWER BOUND")
    a(
        "> **Measurement caveat (a finding in itself):** origin is inferred from "
        "the `hydraflow-find` label, but the factory files most of its churn "
        "(wiki, arch-regen, UL, bot-PRs) *unlabelled* and under a human token — so "
        "the 'Unclassified' column below is largely self-sourced work this proxy "
        "cannot see. The self-fraction here is a **lower bound**; the true value is "
        "much higher. Cleanly measuring self-vs-external origin needs the "
        "provenance telemetry #10825 calls for — the factory currently cannot "
        "measure its own wake."
    )
    if fp.self_series:
        slope = trend_slope(fp.self_series)
        first, last = fp.self_series[0], fp.self_series[-1]
        a(
            f"- Labelled self-fraction {_pct(first.self_fraction)} → "
            f"{_pct(last.self_fraction)} (slope {slope:+.3f}/wk) — but see caveat."
        )
        a("")
        a("| Week | Self (labelled) | Pipeline | Unclassified | Self % (LB) |")
        a("|---|---|---|---|---|")
        for p in fp.self_series:
            a(
                f"| {p.week_start:%m-%d} | {p.self_count} | {p.pipeline_count} "
                f"| {p.external_count} | {_pct(p.self_fraction)} |"
            )
    else:
        a("_No issues in window._")
    a("")
    a("### 2. Rework ratio (merges touching files merged < 14d prior)")
    a(
        f"- **{_pct(fp.rework.ratio)}** ({fp.rework.reworked_merges}/"
        f"{fp.rework.total_merges} merges), **excluding** deterministic regen "
        "artifacts (`docs/arch/generated/*`, `.meta.json`) — those are rewritten "
        "every PR and would otherwise dominate the signal falsely."
    )
    if fp.rework.hot_paths:
        a("- Hottest re-worked paths:")
        for path, n in fp.rework.hot_paths[:5]:
            a(f"  - `{path}` ×{n}")
    a("")
    a("### 3. Verdict flapping (ConvergenceOscillationLoop escalations)")
    a(f"- {fp.flapping.total_escalations} escalation(s) in window.")
    if fp.flapping.is_fleet_level_evidence:
        a(
            "- **Zero per-item escalations.** Per #10820, this is positive evidence "
            "that the observed flux was **fleet-level** (uncoordinated loops), not "
            "per-item cross-boundary oscillation — exactly the hypothesis."
        )
    else:
        for stage, n in fp.flapping.per_stage:
            a(f"  - `{stage}` ×{n}")
    a(
        f"- Firing during the quiet fortnight (2026-07-14..07-28): "
        f"**{'yes' if fp.flapping.fired_in_probe_window else 'no'}**."
    )
    a("")
    a("### 4. Flat finders (steady output regardless of demand)")
    flat = [f for f in fp.finders if f.is_flat]
    if flat:
        for f in flat:
            a(f"- `{f.finder}` — {f.total} issues, {f.weekly_counts} (low variance)")
    else:
        a("_No finder met the flat-output threshold._")
    a("")
    a("### 5. Saturation markers (cost-budget cap events)")
    if fp.saturation:
        a(
            f"- {len(fp.saturation)} cap event(s): "
            + ", ".join(f"{d:%m-%d}" for d in fp.saturation)
        )
    else:
        a("_No cost-budget cap issues in window (cap may be unset — see gaps)._")
    a("")
    a("### Classification: fast-tick loops (damper-0a #10843 candidates)")
    if fp.fast_ticks:
        a("Loops ticking faster than hourly — flagged for tick-vs-window review:")
        for lp in fp.fast_ticks[:12]:
            a(f"- `{lp.name}` — {lp.tick_seconds}s")
    a("")
    if fp.gaps:
        a("## Known gaps (underivable from current telemetry)")
        for g in fp.gaps:
            a(f"- {g}")
    a("")
    return "\n".join(lines)

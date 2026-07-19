"""Per-skill telemetry efficiency rollup — spec §5 (telemetry consumption).

Pure math over `PromptTelemetry.get_source_totals()` snapshots. Consumed by
`SkillPromptEvalLoop`'s weekly tick: a ranked scorecard for the cycle summary,
refine-queue ordering (most cost-inefficient skill's regression gets first
crack at the weekly refine cap), and `prompt-inefficiency` issue filing when a
source's cost-per-call has degraded past `INEFFICIENCY_THRESHOLD` vs the
trailing weekly baseline.

No I/O here — the loop owns constructing `PromptTelemetry`, reading/writing
the baseline snapshot in state, and filing issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A source whose cost-per-call rose more than 50% vs. the trailing weekly
# baseline is "inefficient" enough to warrant a filed issue (spec §5c).
INEFFICIENCY_THRESHOLD = 0.5


@dataclass
class SkillEfficiencyRow:
    """One row of the weekly per-source efficiency scorecard.

    ``calls``/``est_cost_usd`` are LIFETIME-CUMULATIVE (straight from
    `PromptTelemetry.get_source_totals()`). ``cost_per_call`` is NOT simply
    ``est_cost_usd / calls`` — it is this tick's marginal *window*
    cost-per-call (``delta_cost / delta_calls`` since the baseline snapshot)
    when there was window activity, falling back to the cumulative
    lifetime average only when there wasn't (no baseline, no new calls this
    tick, or a counter reset). See `compute_skill_efficiency`.
    """

    source: str
    calls: int
    est_cost_usd: float
    anomalies: int
    cost_per_call: float
    trend_vs_baseline: float | None


def _cost_and_calls(totals: dict[str, int]) -> tuple[float, int]:
    """Derive ``(est_cost_usd, calls)`` from one aggregate counter dict.

    ``estimated_cost_microusd`` is the real accumulator key added to
    `PromptTelemetry._new_counter()`/`_accumulate_counter()` alongside this
    module (int, so it survives `get_source_totals()`'s int-only filter —
    unlike the pre-existing float `estimated_cost_usd` accumulator).
    """
    calls = int(totals.get("inference_calls", 0))
    est_cost_usd = int(totals.get("estimated_cost_microusd", 0)) / 1_000_000
    return est_cost_usd, calls


def compute_skill_efficiency(
    totals_by_source: dict[str, dict[str, int]],
    baseline: dict[str, dict[str, int]] | None,
) -> list[SkillEfficiencyRow]:
    """Roll up per-source telemetry totals into ranked efficiency rows.

    ``totals_by_source`` (current) and ``baseline`` (previous tick) are BOTH
    LIFETIME-CUMULATIVE snapshots straight from
    `PromptTelemetry.get_source_totals()` — the accumulator never resets, so
    a source with a long history has a huge lifetime call count. Comparing
    the two snapshots' cumulative averages directly would dilute any real
    regression into noise (e.g. a genuine 100x-cost blowup over 100 calls on
    a source with 100k lifetime calls barely moves the lifetime average).
    Instead we derive the *marginal window* since baseline:

    - ``delta_calls = current.calls - baseline.calls``,
      ``delta_cost = current.est_cost_usd - baseline.est_cost_usd``.
    - Window cost-per-call = ``delta_cost / delta_calls`` when
      ``delta_calls > 0``. A zero or negative delta (no new calls this tick,
      or a counter reset/file rotation dropping the lifetime total below the
      stored baseline) means there's no window to measure — the window
      cost-per-call and ``trend_vs_baseline`` are both ``None`` in that case.
    - The baseline reference point is the baseline snapshot's own cumulative
      average (``baseline.est_cost_usd / baseline.calls``), not a window —
      there's nothing before "baseline" to window against. ``None`` when the
      baseline has no entry for the source or its call count is zero.
    - ``trend_vs_baseline`` is the fractional change of window cost-per-call
      vs. that baseline average, when both are defined and the baseline
      average is nonzero (nothing to divide by otherwise — a genuine "new
      source" or "was free" case, not a regression).

    ``SkillEfficiencyRow.cost_per_call`` (and the worst-first SORT below) use
    the window cost-per-call when it's defined; otherwise they fall back to
    the source's cumulative lifetime average so the scorecard still shows a
    meaningful rate for a source with no baseline/no window activity instead
    of a bare zero.
    """
    baseline_map = baseline if isinstance(baseline, dict) else {}
    rows: list[SkillEfficiencyRow] = []
    for source, totals in totals_by_source.items():
        cum_cost_usd, cum_calls = _cost_and_calls(totals)
        anomalies = int(totals.get("usage_unavailable_calls", 0))
        cumulative_cost_per_call = cum_cost_usd / cum_calls if cum_calls else 0.0

        window_cost_per_call: float | None = None
        base_cost_per_call: float | None = None
        base_totals = baseline_map.get(source)
        if isinstance(base_totals, dict):
            base_cost_usd, base_calls = _cost_and_calls(base_totals)
            base_cost_per_call = base_cost_usd / base_calls if base_calls else None
            delta_calls = cum_calls - base_calls
            if delta_calls > 0:
                delta_cost = cum_cost_usd - base_cost_usd
                window_cost_per_call = delta_cost / delta_calls

        trend: float | None = None
        if (
            window_cost_per_call is not None
            and base_cost_per_call is not None
            and base_cost_per_call > 0
        ):
            trend = (window_cost_per_call - base_cost_per_call) / base_cost_per_call

        cost_per_call = (
            window_cost_per_call
            if window_cost_per_call is not None
            else cumulative_cost_per_call
        )

        rows.append(
            SkillEfficiencyRow(
                source=source,
                calls=cum_calls,
                est_cost_usd=cum_cost_usd,
                anomalies=anomalies,
                cost_per_call=cost_per_call,
                trend_vs_baseline=trend,
            )
        )
    rows.sort(key=lambda r: r.cost_per_call, reverse=True)
    return rows


def format_scorecard(rows: list[SkillEfficiencyRow]) -> str:
    """Render *rows* (already worst-first) as a markdown table.

    ``calls``/``est_cost_usd`` are lifetime-cumulative; ``cost_per_call`` is
    this tick's marginal window rate (falling back to the cumulative average
    when there's no window to measure) — see `compute_skill_efficiency`. The
    header spells this out so the table isn't mistaken for two cumulative
    columns that happen to disagree.
    """
    header = (
        "| skill | calls (lifetime) | est_cost_usd (lifetime) "
        "| cost_per_call (window) | anomalies | trend_vs_baseline |"
    )
    sep = "|---|---|---|---|---|---|"
    lines = [header, sep]
    for row in rows:
        trend = (
            f"{row.trend_vs_baseline:+.0%}"
            if row.trend_vs_baseline is not None
            else "n/a"
        )
        lines.append(
            f"| {row.source} | {row.calls} | ${row.est_cost_usd:.4f} "
            f"| ${row.cost_per_call:.4f} | {row.anomalies} | {trend} |"
        )
    return "\n".join(lines)


def pick_refine_order(
    cases: list[dict[str, Any]], rows: list[SkillEfficiencyRow]
) -> list[dict[str, Any]]:
    """Reorder *cases* so the most cost-inefficient skill's case goes first.

    *cases* is the unfiltered corpus-run output (not pre-filtered to
    regressions) — the caller feeds the full case list and this function
    just reorders it; callers decide separately which cases actually count
    as a regression. *rows* is already worst-first (see
    `compute_skill_efficiency`), so a case's rank is its
    ``expected_catcher``'s position in *rows*. Cases whose catcher has no
    telemetry row sort last, keeping their original relative order (`sorted`
    is stable) — "most-inefficient skill first, stable otherwise".
    """
    rank = {row.source: i for i, row in enumerate(rows)}
    unranked = len(rows)
    return sorted(
        cases,
        key=lambda case: rank.get(str(case.get("expected_catcher", "")), unranked),
    )

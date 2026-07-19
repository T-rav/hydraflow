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
    """One row of the weekly per-source efficiency scorecard."""

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

    Sorted worst-first by ``cost_per_call`` — both the scorecard and
    `pick_refine_order` want the most expensive-per-call source first.
    ``trend_vs_baseline`` is the fractional change in cost-per-call versus the
    matching *baseline* entry: ``None`` when *baseline* has no entry for the
    source, or when the baseline's cost-per-call was zero (nothing to divide
    by — a genuine "new source" or "was free" case, not a regression).
    """
    baseline_map = baseline if isinstance(baseline, dict) else {}
    rows: list[SkillEfficiencyRow] = []
    for source, totals in totals_by_source.items():
        est_cost_usd, calls = _cost_and_calls(totals)
        anomalies = int(totals.get("usage_unavailable_calls", 0))
        cost_per_call = est_cost_usd / calls if calls else 0.0

        trend: float | None = None
        base_totals = baseline_map.get(source)
        if isinstance(base_totals, dict):
            base_cost_usd, base_calls = _cost_and_calls(base_totals)
            base_cost_per_call = base_cost_usd / base_calls if base_calls else 0.0
            if base_cost_per_call > 0:
                trend = (cost_per_call - base_cost_per_call) / base_cost_per_call

        rows.append(
            SkillEfficiencyRow(
                source=source,
                calls=calls,
                est_cost_usd=est_cost_usd,
                anomalies=anomalies,
                cost_per_call=cost_per_call,
                trend_vs_baseline=trend,
            )
        )
    rows.sort(key=lambda r: r.cost_per_call, reverse=True)
    return rows


def format_scorecard(rows: list[SkillEfficiencyRow]) -> str:
    """Render *rows* (already worst-first) as a markdown table."""
    header = (
        "| skill | calls | est_cost_usd | cost_per_call | anomalies "
        "| trend_vs_baseline |"
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
    regressed_cases: list[dict[str, Any]], rows: list[SkillEfficiencyRow]
) -> list[dict[str, Any]]:
    """Reorder *regressed_cases* so the most cost-inefficient skill goes first.

    *rows* is already worst-first (see `compute_skill_efficiency`), so a
    case's rank is its ``expected_catcher``'s position in *rows*. Cases whose
    catcher has no telemetry row sort last, keeping their original relative
    order (`sorted` is stable) — "most-inefficient skill first, stable
    otherwise".
    """
    rank = {row.source: i for i, row in enumerate(rows)}
    unranked = len(rows)
    return sorted(
        regressed_cases,
        key=lambda case: rank.get(str(case.get("expected_catcher", "")), unranked),
    )

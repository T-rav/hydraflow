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
# baseline is "inefficient" enough to warrant a filed issue.
INEFFICIENCY_THRESHOLD = 0.5

# #11133/#11140: a marginal window smaller than this carries no regression
# evidence — a 1-3 call window's cost-per-call is dominated by per-call
# variance, and the 2026-08-14 idle run filed "regressions" (and reordered
# the refine queue) off exactly such windows. Below the floor the window
# rate and trend are None: insufficient evidence, not a measurement.
MIN_WINDOW_CALLS = 5


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
    # #11118 evidence fields: the numbers that would falsify a filing.
    #: Effective (usage-bearing) calls in this tick's marginal window; None
    #: when there was no window at all (no baseline entry, no new raw calls,
    #: or a counter reset).
    window_calls: int | None = None
    #: The baseline reference rate the trend was computed against.
    base_cost_per_call: float | None = None
    #: #11117: every RAW call in this tick's window recorded zero usage —
    #: the source is burning spawns the telemetry cannot see (563 straight
    #: term_proposer calls in the claude/sonnet era). An operational alert,
    #: distinct from a cost regression.
    zero_usage_window: bool = False


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


def _effective_calls(totals: dict[str, int]) -> int:
    """Calls that produced observable usage (#11117 data hygiene).

    A zero-usage call (``usage_status=unavailable``) records cost 0 while
    still counting as a call — 563 such term_proposer calls DEFLATED its
    cost-per-call for four days, so the first tick of real usage read as a
    massive "regression". Cost-per-call denominators therefore count only
    usage-bearing calls; the raw call count stays on the row for honesty.
    """
    calls = int(totals.get("inference_calls", 0))
    zero_usage = int(totals.get("usage_unavailable_calls", 0))
    return max(0, calls - zero_usage)


def _effective_cost_usd(totals: dict[str, int]) -> float:
    """Cost attributable to usage-bearing calls (#11117 same-population rule).

    Zero-usage calls are excluded from every rate DENOMINATOR, so the
    char-estimated cost some of them still record (small-prompt successes
    below the anomaly threshold) must come out of the NUMERATOR too —
    otherwise window rates inflate: the mirror image of the deflation bug.
    ``unavailable_est_cost_microusd`` is the parallel accumulator
    `PromptTelemetry._accumulate_counter` keeps for exactly this
    subtraction; clamped at zero for pre-migration snapshots.
    """
    total = int(totals.get("estimated_cost_microusd", 0))
    unavailable = int(totals.get("unavailable_est_cost_microusd", 0))
    return max(0, total - unavailable) / 1_000_000


def compute_skill_efficiency(
    totals_by_source: dict[str, dict[str, int]],
    baseline: dict[str, dict[str, int]] | None,
    *,
    min_window_calls: int = MIN_WINDOW_CALLS,
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
    - EVERY per-call denominator counts only *effective* (usage-bearing)
      calls — `_effective_calls`, i.e. raw calls minus
      ``usage_unavailable_calls`` (#11117): a zero-usage call records cost 0
      while still counting as a call, deflating any rate it participates in.
      The raw call count stays on the row (``calls``) for honesty. The
      NUMERATOR mirrors the same population: cost recorded BY zero-usage
      calls (``unavailable_est_cost_microusd`` — small-prompt successes get
      char-estimated cost despite unavailable usage) is subtracted before
      any rate is formed, so numerator and denominator always count the
      same calls.
    - Window cost-per-call = ``delta_cost / delta_effective_calls`` when
      there was raw window activity AND the effective window is at least
      ``min_window_calls`` (#11133/#11140 — a 1-3 call window is variance,
      not evidence). A zero/negative raw delta (no new calls this tick, or a
      counter reset/file rotation dropping the lifetime total below the
      stored baseline) means there's no window to measure. In every
      no-window/under-floor case the window cost-per-call and
      ``trend_vs_baseline`` are both ``None``.
    - A window with raw activity but ZERO effective calls sets
      ``zero_usage_window`` — the source is burning spawns the telemetry
      cannot see (#11117). That's an operational alert for the caller, never
      a rate.
    - The baseline reference point is the baseline snapshot's own cumulative
      average (``baseline.est_cost_usd / baseline.effective_calls``), not a
      window — there's nothing before "baseline" to window against. ``None``
      when the baseline has no entry for the source or its effective call
      count is zero.
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
        cum_effective = _effective_calls(totals)
        cum_effective_cost = _effective_cost_usd(totals)
        anomalies = int(totals.get("usage_unavailable_calls", 0))
        cumulative_cost_per_call = (
            cum_effective_cost / cum_effective if cum_effective else 0.0
        )

        window_cost_per_call: float | None = None
        base_cost_per_call: float | None = None
        window_calls: int | None = None
        zero_usage_window = False
        base_totals = baseline_map.get(source)
        if isinstance(base_totals, dict):
            _, base_raw_calls = _cost_and_calls(base_totals)
            base_effective = _effective_calls(base_totals)
            base_effective_cost = _effective_cost_usd(base_totals)
            base_cost_per_call = (
                base_effective_cost / base_effective if base_effective else None
            )
            if cum_calls - base_raw_calls > 0:
                window_calls = max(cum_effective - base_effective, 0)
                zero_usage_window = window_calls == 0
                if window_calls >= min_window_calls:
                    delta_cost = cum_effective_cost - base_effective_cost
                    window_cost_per_call = delta_cost / window_calls

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
                window_calls=window_calls,
                base_cost_per_call=base_cost_per_call,
                zero_usage_window=zero_usage_window,
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
        "| cost_per_call (window) | window_calls | anomalies "
        "| trend_vs_baseline |"
    )
    sep = "|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for row in rows:
        trend = (
            f"{row.trend_vs_baseline:+.0%}"
            if row.trend_vs_baseline is not None
            else "n/a"
        )
        window = str(row.window_calls) if row.window_calls is not None else "n/a"
        lines.append(
            f"| {row.source} | {row.calls} | ${row.est_cost_usd:.4f} "
            f"| ${row.cost_per_call:.4f} | {window} | {row.anomalies} | {trend} |"
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

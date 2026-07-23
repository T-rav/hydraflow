"""Tests for prompt_efficiency.py (spec §5 — telemetry consumption).

Aggregate dicts here mirror the REAL keys `PromptTelemetry._new_counter()` /
`_accumulate_counter()` produce (see `src/prompt_telemetry.py`), not the
placeholder names from the task brief: `inference_calls`,
`estimated_cost_microusd` (int, added alongside this feature — see
`tests/test_prompt_telemetry.py::TestEstimatedCostMicrousdAccumulator`), and
`usage_unavailable_calls` (the existing per-source "did usage come back?"
anomaly counter).

`get_source_totals()` is LIFETIME-CUMULATIVE — never reset — so both
``totals_by_source`` and ``baseline`` here model realistic cumulative
snapshots one tick apart (baseline calls/cost <= current calls/cost), not
single-window totals. See `compute_skill_efficiency`'s docstring for the
marginal-window math this exercises.
"""

from __future__ import annotations

from prompt_efficiency import (
    INEFFICIENCY_THRESHOLD,
    SkillEfficiencyRow,
    compute_skill_efficiency,
    format_scorecard,
    pick_refine_order,
)


def _totals(cost_microusd: int, calls: int, anomalies: int = 0) -> dict[str, int]:
    return {
        "inference_calls": calls,
        "estimated_cost_microusd": cost_microusd,
        "usage_unavailable_calls": anomalies,
    }


def test_rows_sorted_worst_first() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(10_000_000, 10), "scope-check": _totals(1_000_000, 10)},
        baseline=None,
    )
    assert [r.source for r in rows] == ["diff-sanity", "scope-check"]


def test_row_math_is_derived_correctly() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(10_000_000, 10, anomalies=2)}, baseline=None
    )
    row = rows[0]
    assert row.calls == 10
    assert row.est_cost_usd == 10.0
    assert row.anomalies == 2
    # No baseline => no window to measure => falls back to cumulative average.
    assert row.cost_per_call == 1.0
    assert row.trend_vs_baseline is None


def test_trend_vs_baseline_uses_marginal_window_not_lifetime_cumulative() -> None:
    """The reviewer's concrete case (#9724 finding 1): a source with a long
    lifetime history (100k calls) regresses 100x over a 100-call window.
    Comparing cumulative averages directly would dilute this into ~9.9% —
    far under `INEFFICIENCY_THRESHOLD` — and the feature could never fire
    for any source with history. Marginal-window math must isolate the
    100-call window's actual $1.00/call rate and compare it against the
    baseline's $0.01/call cumulative average.
    """
    baseline = {"diff-sanity": _totals(1_000_000_000, 100_000)}  # $1000 / 100k calls
    current = {"diff-sanity": _totals(1_100_000_000, 100_100)}  # +$100 / +100 calls
    rows = compute_skill_efficiency(current, baseline=baseline)
    row = rows[0]

    # Window cost-per-call: 100 new calls costing $1.00 each this tick.
    assert row.cost_per_call == 1.0
    assert row.trend_vs_baseline is not None
    assert row.trend_vs_baseline == 99.0
    assert row.trend_vs_baseline > INEFFICIENCY_THRESHOLD


def test_trend_is_none_without_matching_baseline_source() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"scope-check": _totals(1_000_000, 10)},
    )
    assert rows[0].trend_vs_baseline is None
    # No baseline entry for this source => cost_per_call falls back to the
    # cumulative average.
    assert rows[0].cost_per_call == 0.3


def test_trend_is_none_when_baseline_cost_per_call_is_zero() -> None:
    """Baseline had calls but zero cost (e.g. all-free/cached calls) — no
    rate to compare against, even though there was window activity."""
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 110)},
        baseline={"diff-sanity": _totals(0, 100)},
    )
    assert rows[0].trend_vs_baseline is None


def test_trend_is_none_when_delta_calls_is_zero() -> None:
    """No new calls since baseline (delta_calls == 0) => no window to
    measure => trend is None and cost_per_call falls back to the
    cumulative average, not a division by zero."""
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"diff-sanity": _totals(1_000_000, 10)},
    )
    assert rows[0].trend_vs_baseline is None
    assert rows[0].cost_per_call == 0.3


def test_trend_is_none_when_delta_calls_is_negative() -> None:
    """A negative delta (counter reset / file rotation dropping the lifetime
    total below the stored baseline) must not be read as a window — treat
    it as no-window-data => None, not a negative or nonsensical rate."""
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(500_000, 5)},
        baseline={"diff-sanity": _totals(1_000_000, 10)},
    )
    assert rows[0].trend_vs_baseline is None
    # Falls back to the (post-reset) cumulative average, not a negative
    # window rate.
    assert rows[0].cost_per_call == 0.1


def test_zero_calls_does_not_raise_zero_division() -> None:
    rows = compute_skill_efficiency({"diff-sanity": _totals(0, 0)}, baseline=None)
    assert rows[0].calls == 0
    assert rows[0].cost_per_call == 0.0


def test_pick_refine_order_prefers_inefficient_skill() -> None:
    rows = compute_skill_efficiency(
        {
            "test-adequacy": _totals(9_000_000, 10),
            "diff-sanity": _totals(1_000_000, 10),
        },
        baseline=None,
    )
    cases = [
        {"case_id": "a", "expected_catcher": "diff-sanity"},
        {"case_id": "b", "expected_catcher": "test-adequacy"},
    ]
    assert [c["case_id"] for c in pick_refine_order(cases, rows)] == ["b", "a"]


def test_pick_refine_order_is_stable_for_unranked_cases() -> None:
    """Cases whose catcher has no telemetry row keep their relative order."""
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_000_000, 10)}, baseline=None
    )
    cases = [
        {"case_id": "a", "expected_catcher": "unknown-skill"},
        {"case_id": "b", "expected_catcher": "also-unknown"},
        {"case_id": "c", "expected_catcher": "diff-sanity"},
    ]
    # diff-sanity has the only row, so "c" ranks first; "a"/"b" (unranked)
    # keep their original relative order behind it.
    assert [c["case_id"] for c in pick_refine_order(cases, rows)] == ["c", "a", "b"]


def test_scorecard_is_markdown_table() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_000_000, 10)}, baseline=None
    )
    out = format_scorecard(rows)
    assert out.startswith("| skill ")
    assert "diff-sanity" in out


def test_scorecard_renders_trend_as_percent_or_na() -> None:
    # Cumulative baseline: 100 calls / $1.00 total ($0.01/call). Current tick
    # adds 10 more calls costing $0.30 total ($0.03/call window rate) — a
    # +200% trend vs. the baseline's cumulative average.
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_300_000, 110)},
        baseline={"diff-sanity": _totals(1_000_000, 100)},
    )
    out = format_scorecard(rows)
    assert "+200%" in out

    no_baseline_rows = [
        SkillEfficiencyRow(
            source="scope-check",
            calls=1,
            est_cost_usd=0.1,
            anomalies=0,
            cost_per_call=0.1,
            trend_vs_baseline=None,
        )
    ]
    assert "n/a" in format_scorecard(no_baseline_rows)


def test_scorecard_empty_rows_is_header_only() -> None:
    out = format_scorecard([])
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("| skill ")

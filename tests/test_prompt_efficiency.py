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

import pytest

from prompt_efficiency import (
    INEFFICIENCY_THRESHOLD,
    MIN_WINDOW_CALLS,
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
    # #11117: the denominator counts only usage-bearing calls (10 - 2 = 8) —
    # zero-usage calls record cost 0 and would deflate the rate.
    assert row.cost_per_call == 1.25
    assert row.trend_vs_baseline is None
    assert row.window_calls is None
    assert row.zero_usage_window is False


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


def test_under_sampled_window_yields_no_trend() -> None:
    """#11133/#11140: a window below MIN_WINDOW_CALLS is variance, not
    evidence — the 2026-08-14 idle run filed 'regressions' (and reordered
    the refine queue) off 1-3 call windows. Even a 10x per-call spike over
    2 calls must not produce a window rate or a trend."""
    assert MIN_WINDOW_CALLS > 2
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_200_000, 102)},  # +2 calls at $0.10 each
        baseline={"diff-sanity": _totals(1_000_000, 100)},  # $0.01/call
    )
    row = rows[0]
    assert row.trend_vs_baseline is None
    assert row.window_calls == 2
    # Falls back to the cumulative average instead of the 2-call rate.
    assert row.cost_per_call == 1.2 / 102


def test_window_at_floor_yields_trend() -> None:
    baseline = {"diff-sanity": _totals(1_000_000, 100)}  # $0.01/call
    current = {
        "diff-sanity": _totals(
            1_000_000 + MIN_WINDOW_CALLS * 100_000, 100 + MIN_WINDOW_CALLS
        )
    }  # floor-sized window at $0.10/call
    rows = compute_skill_efficiency(current, baseline=baseline)
    row = rows[0]
    assert row.window_calls == MIN_WINDOW_CALLS
    assert row.cost_per_call == pytest.approx(0.1)
    assert row.trend_vs_baseline == pytest.approx(9.0)


def test_zero_usage_calls_excluded_from_denominators() -> None:
    """#11117: zero-usage calls (cost 0, still counted as calls) must not
    deflate cost-per-call. Baseline: 563 zero-usage calls + 37 real calls
    at ~$0.054 — the raw-denominator rate would be ~$0.0033/call, so 10 new
    real calls at the UNCHANGED $0.054 rate would read as a huge fake
    regression. Effective denominators keep the trend flat."""
    baseline = {
        "term_proposer": _totals(2_000_000, 600, anomalies=563)  # $2 / 37 real
    }
    current = {
        "term_proposer": _totals(2_540_000, 610, anomalies=563)  # +$0.54 / +10 real
    }
    rows = compute_skill_efficiency(current, baseline=baseline)
    row = rows[0]
    assert row.base_cost_per_call is not None
    assert abs(row.base_cost_per_call - 2.0 / 37) < 1e-9
    assert row.window_calls == 10
    assert row.cost_per_call == pytest.approx(0.054)
    assert row.trend_vs_baseline is not None
    assert abs(row.trend_vs_baseline) < INEFFICIENCY_THRESHOLD


def test_estimated_cost_of_zero_usage_calls_excluded_from_numerator() -> None:
    """Review find on #11117: small-prompt zero-usage calls still record
    char-ESTIMATED cost. Excluding them from the denominator but not the
    numerator would INFLATE the window rate — the mirror image of the
    deflation FP. `unavailable_est_cost_microusd` keeps the numerator on
    the same population."""
    baseline = {"diff-sanity": _totals(1_000_000, 100)}  # $0.01/call, all real
    # Window: +5 real calls at $0.01 ($0.05) plus 20 zero-usage calls that
    # each picked up $0.002 char-estimated cost ($0.04). A full-cost
    # numerator would read 0.09/5 = $0.018/call — a fake +80% trend.
    current_totals = _totals(1_090_000, 125, anomalies=20)
    current_totals["unavailable_est_cost_microusd"] = 40_000
    row = compute_skill_efficiency({"diff-sanity": current_totals}, baseline=baseline)[
        0
    ]
    assert row.window_calls == 5
    assert row.cost_per_call == pytest.approx(0.01)
    assert row.trend_vs_baseline == pytest.approx(0.0, abs=1e-9)


def test_all_zero_usage_window_sets_flag_not_rate() -> None:
    """#11117: raw window activity whose every call is zero-usage is a
    telemetry blind spot, not a measurable rate."""
    rows = compute_skill_efficiency(
        {"term_proposer": _totals(1_000_000, 120, anomalies=30)},
        baseline={"term_proposer": _totals(1_000_000, 100, anomalies=10)},
    )
    row = rows[0]
    assert row.zero_usage_window is True
    assert row.window_calls == 0
    assert row.trend_vs_baseline is None


def test_single_zero_usage_call_does_not_flag_blind_spot() -> None:
    """#11167 (re-audit find): one stray unavailable call (small prompts
    legitimately record no usage) is n=1 evidence — the blind-spot flag
    needs the same MIN_WINDOW_CALLS floor as the regression path."""
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_000_000, 1001, anomalies=201)},
        baseline={"diff-sanity": _totals(1_000_000, 1000, anomalies=200)},
    )
    assert rows[0].zero_usage_window is False


def test_no_window_activity_does_not_set_zero_usage_flag() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(1_000_000, 100, anomalies=10)},
        baseline={"diff-sanity": _totals(1_000_000, 100, anomalies=10)},
    )
    assert rows[0].zero_usage_window is False
    assert rows[0].window_calls is None


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

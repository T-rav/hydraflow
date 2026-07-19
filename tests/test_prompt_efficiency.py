"""Tests for prompt_efficiency.py (spec §5 — telemetry consumption).

Aggregate dicts here mirror the REAL keys `PromptTelemetry._new_counter()` /
`_accumulate_counter()` produce (see `src/prompt_telemetry.py`), not the
placeholder names from the task brief: `inference_calls`,
`estimated_cost_microusd` (int, added alongside this feature — see
`tests/test_prompt_telemetry.py::TestEstimatedCostMicrousdAccumulator`), and
`usage_unavailable_calls` (the existing per-source "did usage come back?"
anomaly counter).
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
    assert row.cost_per_call == 1.0
    assert row.trend_vs_baseline is None


def test_trend_vs_baseline() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"diff-sanity": _totals(1_000_000, 10)},
    )
    assert rows[0].trend_vs_baseline is not None
    assert rows[0].trend_vs_baseline > INEFFICIENCY_THRESHOLD


def test_trend_is_none_without_matching_baseline_source() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"scope-check": _totals(1_000_000, 10)},
    )
    assert rows[0].trend_vs_baseline is None


def test_trend_is_none_when_baseline_cost_per_call_is_zero() -> None:
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"diff-sanity": _totals(0, 10)},
    )
    assert rows[0].trend_vs_baseline is None


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
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(3_000_000, 10)},
        baseline={"diff-sanity": _totals(1_000_000, 10)},
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

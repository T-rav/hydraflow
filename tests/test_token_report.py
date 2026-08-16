"""Tests for token_report.py — the #11298 measurement layer."""

from __future__ import annotations

from token_report import MIN_ISSUE_TOKENS, build_token_report


def _row(
    issue: int,
    source: str,
    tokens: int,
    *,
    input_tokens: int = 0,
    cache_read: int = 0,
    cost: float = 0.0,
) -> dict:
    return {
        "issue_number": issue,
        "source": source,
        "total_tokens": tokens,
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_read,
        "estimated_cost_usd": cost,
    }


def test_per_issue_phase_breakdown_sorted_desc() -> None:
    rows = [
        _row(7, "planner", 30_000, cost=0.30),
        _row(7, "implementer", 100_000, cost=1.00),
        _row(7, "reviewer", 50_000, cost=0.50),
    ]
    report = build_token_report(rows)
    assert report["fleet"]["issues_counted"] == 1
    entry = report["issues"][0]
    assert entry["issue"] == 7
    assert entry["tokens"] == 180_000
    assert entry["spawns"] == 3
    assert [p["source"] for p in entry["phases"]] == [
        "implementer",
        "reviewer",
        "planner",
    ]


def test_cache_hit_rate_computed_from_actual_usage_only() -> None:
    rows = [
        _row(7, "implementer", 50_000, input_tokens=10_000, cache_read=90_000),
        _row(7, "implementer", 50_000, input_tokens=0, cache_read=0),  # estimate-only
    ]
    entry = build_token_report(rows)["issues"][0]
    assert entry["cache_hit_rate"] == 0.9


def test_cache_hit_rate_none_when_no_actual_usage() -> None:
    rows = [_row(7, "implementer", 50_000)]
    entry = build_token_report(rows)["issues"][0]
    assert entry["cache_hit_rate"] is None


def test_tiny_issues_excluded_from_report() -> None:
    rows = [
        _row(1, "dedup", MIN_ISSUE_TOKENS - 1),
        _row(2, "implementer", 80_000),
    ]
    report = build_token_report(rows)
    assert [e["issue"] for e in report["issues"]] == [2]


def test_fleet_rollup_and_phase_share() -> None:
    rows = [
        _row(1, "implementer", 60_000),
        _row(1, "planner", 40_000),
        _row(2, "implementer", 100_000),
    ]
    fleet = build_token_report(rows)["fleet"]
    assert fleet["issues_counted"] == 2
    assert fleet["median_tokens_per_issue"] in (100_000,)
    assert fleet["mean_tokens_per_issue"] == 100_000
    share = {p["source"]: p["share"] for p in fleet["phase_share"]}
    assert share["implementer"] == 0.8
    assert share["planner"] == 0.2


def test_recent_issues_cap_keeps_newest() -> None:
    rows = []
    for issue in range(1, 40):  # oldest -> newest
        rows.append(_row(issue, "implementer", 10_000))
    report = build_token_report(rows, recent_issues=5)
    assert [e["issue"] for e in report["issues"]] == [39, 38, 37, 36, 35]


def test_estimate_fallback_when_no_actual_total() -> None:
    row = {
        "issue_number": 3,
        "source": "planner",
        "total_tokens": 0,
        "total_est_tokens": 20_000,
    }
    entry = build_token_report([row])["issues"][0]
    assert entry["tokens"] == 20_000

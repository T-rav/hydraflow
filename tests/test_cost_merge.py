"""Unit tests for the cross-repo cost-rollup merges (Phase 3c-2).

Each merge folds several per-repo builder payloads into the aggregate the
``repo=__all__`` Factory Cost endpoints return: group-by-sum on the phase /
loop / model dimensions, with per-issue rows kept distinct by repo.
"""

from __future__ import annotations

from dashboard_routes._cost_merge import (
    merge_by_loop,
    merge_cost_by_model,
    merge_per_loop_cost,
    merge_rolling_24h,
    merge_top_issues,
)


def test_merge_rolling_24h_sums_totals_and_breakdowns():
    a = {
        "generated_at": "2026-06-08T10:00:00+00:00",
        "window_hours": 24,
        "total": {"cost_usd": 1.5, "tokens_in": 100, "tokens_out": 50},
        "by_phase": [
            {"phase": "implement", "cost_usd": 1.5, "tokens_in": 100, "tokens_out": 50}
        ],
        "by_loop": [{"loop": "rc_budget", "ticks": 2, "wall_clock_seconds": 4}],
    }
    b = {
        "generated_at": "2026-06-08T11:00:00+00:00",
        "window_hours": 24,
        "total": {"cost_usd": 2.5, "tokens_in": 200, "tokens_out": 75},
        "by_phase": [
            {"phase": "implement", "cost_usd": 2.0, "tokens_in": 150, "tokens_out": 50},
            {"phase": "review", "cost_usd": 0.5, "tokens_in": 50, "tokens_out": 25},
        ],
        "by_loop": [{"loop": "rc_budget", "ticks": 3, "wall_clock_seconds": 6}],
    }
    merged = merge_rolling_24h([a, b])
    assert merged["total"] == {"cost_usd": 4.0, "tokens_in": 300, "tokens_out": 125}
    # Latest stamp wins; window is constant.
    assert merged["generated_at"] == "2026-06-08T11:00:00+00:00"
    assert merged["window_hours"] == 24
    by_phase = {r["phase"]: r for r in merged["by_phase"]}
    assert by_phase["implement"]["cost_usd"] == 3.5
    assert by_phase["implement"]["tokens_in"] == 250
    assert by_phase["review"]["cost_usd"] == 0.5
    assert merged["by_loop"] == [
        {"loop": "rc_budget", "ticks": 5, "wall_clock_seconds": 10}
    ]


def test_merge_rolling_24h_single_element_is_identity():
    one = {
        "generated_at": "2026-06-08T10:00:00+00:00",
        "window_hours": 24,
        "total": {"cost_usd": 1.5, "tokens_in": 100, "tokens_out": 50},
        "by_phase": [
            {"phase": "implement", "cost_usd": 1.5, "tokens_in": 100, "tokens_out": 50}
        ],
        "by_loop": [{"loop": "rc_budget", "ticks": 2, "wall_clock_seconds": 4}],
    }
    assert merge_rolling_24h([one]) == one


def test_merge_top_issues_tags_repo_and_keeps_collisions_distinct():
    a = [{"issue": 1, "cost_usd": 5.0, "wall_clock_seconds": 10}]
    b = [{"issue": 1, "cost_usd": 3.0, "wall_clock_seconds": 8}]
    merged = merge_top_issues([("org-a", a), ("org-b", b)], limit=10)
    # Same issue number in two repos → two distinct rows, each repo-tagged.
    assert len(merged) == 2
    assert {(r["issue"], r["repo"]) for r in merged} == {(1, "org-a"), (1, "org-b")}
    # Sorted descending by cost.
    assert merged[0]["repo"] == "org-a"


def test_merge_top_issues_global_limit_after_union():
    a = [{"issue": 1, "cost_usd": 9.0, "wall_clock_seconds": 1}]
    b = [
        {"issue": 2, "cost_usd": 8.0, "wall_clock_seconds": 1},
        {"issue": 3, "cost_usd": 1.0, "wall_clock_seconds": 1},
    ]
    merged = merge_top_issues([("org-a", a), ("org-b", b)], limit=2)
    assert [r["issue"] for r in merged] == [1, 2]


def test_merge_by_loop_sums_and_recomputes_share():
    a = [{"loop": "triage", "ticks": 1, "wall_clock_seconds": 2, "share_of_ticks": 1.0}]
    b = [{"loop": "triage", "ticks": 3, "wall_clock_seconds": 6, "share_of_ticks": 1.0}]
    merged = merge_by_loop([a, b])
    assert merged == [
        {"loop": "triage", "ticks": 4, "wall_clock_seconds": 8, "share_of_ticks": 1.0}
    ]


def test_merge_by_loop_share_across_two_loops():
    a = [{"loop": "triage", "ticks": 1, "wall_clock_seconds": 1, "share_of_ticks": 1.0}]
    b = [{"loop": "plan", "ticks": 3, "wall_clock_seconds": 1, "share_of_ticks": 1.0}]
    merged = {r["loop"]: r["share_of_ticks"] for r in merge_by_loop([a, b])}
    assert merged == {"triage": 0.25, "plan": 0.75}


def test_merge_cost_by_model_groups_and_sorts():
    a = [
        {
            "model": "sonnet",
            "cost_usd": 1.0,
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
    ]
    b = [
        {
            "model": "sonnet",
            "cost_usd": 2.0,
            "calls": 2,
            "input_tokens": 20,
            "output_tokens": 10,
            "cache_read_tokens": 1,
            "cache_write_tokens": 2,
        },
        {
            "model": "haiku",
            "cost_usd": 5.0,
            "calls": 1,
            "input_tokens": 4,
            "output_tokens": 2,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
    ]
    merged = merge_cost_by_model([a, b])
    # Descending by cost → haiku (5.0) then sonnet (3.0).
    assert [r["model"] for r in merged] == ["haiku", "sonnet"]
    sonnet = next(r for r in merged if r["model"] == "sonnet")
    assert sonnet["cost_usd"] == 3.0
    assert sonnet["calls"] == 3
    assert sonnet["input_tokens"] == 30
    assert sonnet["cache_write_tokens"] == 2


def test_merge_per_loop_cost_sums_and_merges_model_breakdown():
    def _row(cost, ticks, model_cost):
        return {
            "loop": "implement",
            "cost_usd": cost,
            "tokens_in": 10,
            "tokens_out": 5,
            "llm_calls": 1,
            "issues_filed": 1,
            "issues_closed": 0,
            "escalations": 0,
            "ticks": ticks,
            "ticks_errored": 0,
            "tick_cost_avg_usd": round(cost / ticks, 6) if ticks else 0.0,
            "wall_clock_seconds": 3,
            "last_tick_at": "2026-06-08T10:00:00+00:00",
            "tick_cost_avg_usd_prev_period": 0.0,
            "model_breakdown": {
                "sonnet": {
                    "cost_usd": model_cost,
                    "calls": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            },
        }

    a = [_row(2.0, 2, 2.0)]
    b = [{**_row(4.0, 2, 4.0), "last_tick_at": "2026-06-08T12:00:00+00:00"}]
    merged = merge_per_loop_cost([a, b])
    assert len(merged) == 1
    row = merged[0]
    assert row["loop"] == "implement"
    assert row["cost_usd"] == 6.0
    assert row["ticks"] == 4
    # avg recomputed from merged cost/ticks, not averaged.
    assert row["tick_cost_avg_usd"] == 1.5
    # latest tick stamp wins.
    assert row["last_tick_at"] == "2026-06-08T12:00:00+00:00"
    # model_breakdown folded.
    assert row["model_breakdown"]["sonnet"]["cost_usd"] == 6.0
    assert row["model_breakdown"]["sonnet"]["calls"] == 2


def test_merge_per_loop_cost_zero_ticks_avg_is_zero():
    row = {
        "loop": "idle",
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "llm_calls": 0,
        "issues_filed": 0,
        "issues_closed": 0,
        "escalations": 0,
        "ticks": 0,
        "ticks_errored": 0,
        "tick_cost_avg_usd": 0.0,
        "wall_clock_seconds": 0,
        "last_tick_at": None,
        "tick_cost_avg_usd_prev_period": 0.0,
        "model_breakdown": {},
    }
    merged = merge_per_loop_cost([[row]])
    assert merged[0]["tick_cost_avg_usd"] == 0.0
    assert merged[0]["last_tick_at"] is None

"""Cross-repo stats merge helpers."""

from __future__ import annotations

from dashboard_routes._stats_merge import (
    merge_lifetime_stats,
    merge_pipeline_stats,
    merge_queue_stats,
)
from models import LifetimeStats, PipelineStats, QueueStats, StageStats


def test_merge_queue_stats_sums_maps_and_maxes_timestamp() -> None:
    a = QueueStats(
        queue_depth={"plan": 2, "review": 1},
        in_flight_count=3,
        last_poll_timestamp="2026-06-06T10:00:00",
        dedup_stats={"hits": 5},
    )
    b = QueueStats(
        queue_depth={"plan": 4, "implement": 1},
        in_flight_count=2,
        last_poll_timestamp="2026-06-06T12:00:00",
        dedup_stats={"hits": 1},
    )

    merged = merge_queue_stats([a, b])

    assert merged.queue_depth == {"plan": 6, "review": 1, "implement": 1}
    assert merged.in_flight_count == 5
    assert merged.last_poll_timestamp == "2026-06-06T12:00:00"
    assert merged.dedup_stats == {"hits": 6}


def test_merge_queue_stats_empty() -> None:
    assert merge_queue_stats([]) == QueueStats()


def test_merge_pipeline_stats_merges_stages_and_sums_throughput() -> None:
    a = PipelineStats(
        timestamp="2026-06-06T10:00:00",
        stages={"plan": StageStats(queued=2, active=1, worker_cap=3)},
        uptime_seconds=100.0,
    )
    a.throughput.plan = 4.0
    b = PipelineStats(
        timestamp="2026-06-06T11:00:00",
        stages={"plan": StageStats(queued=1, active=2, worker_cap=2)},
        uptime_seconds=250.0,
    )
    b.throughput.plan = 1.5

    merged = merge_pipeline_stats([a, b])

    assert merged is not None
    assert merged.stages["plan"].queued == 3
    assert merged.stages["plan"].active == 3
    assert merged.stages["plan"].worker_cap == 5
    assert merged.throughput.plan == 5.5
    assert merged.uptime_seconds == 250.0
    assert merged.timestamp == "2026-06-06T11:00:00"


def test_merge_pipeline_stats_empty_is_none() -> None:
    assert merge_pipeline_stats([]) is None


def test_merge_lifetime_concats_durations_and_sums_counters() -> None:
    a = LifetimeStats(
        issues_completed=3,
        plan_durations=[1.0, 2.0],
        fired_thresholds=["t1"],
        retries_per_stage={"42": {"plan": 1}},
    )
    b = LifetimeStats(
        issues_completed=2,
        plan_durations=[3.0],
        fired_thresholds=["t1", "t2"],
        retries_per_stage={"42": {"plan": 2}, "7": {"review": 1}},
    )

    merged = merge_lifetime_stats([a, b])

    assert merged.issues_completed == 5
    # CONCAT (not sum) so percentile math stays correct
    assert merged.plan_durations == [1.0, 2.0, 3.0]
    # union, order-preserving, deduped
    assert merged.fired_thresholds == ["t1", "t2"]
    # merged by issue -> stage
    assert merged.retries_per_stage == {"42": {"plan": 3}, "7": {"review": 1}}


def test_merge_lifetime_empty() -> None:
    assert merge_lifetime_stats([]) == LifetimeStats()

"""Pure helpers that merge per-repo stats into a cross-repo aggregate.

Used by the Work Stream read endpoints when ``repo=__all__``: each per-runtime
stats object is summed/concatenated/maxed field-by-field. Kept pure and
side-effect-free so the merge rules are independently testable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from models import (
    LifetimeStats,
    PipelineStats,
    QueueStats,
    StageStats,
    ThroughputStats,
)


def _sum_int_maps(maps: Iterable[dict[str, int]]) -> dict[str, int]:
    """Key-wise sum of ``dict[str, int]`` maps."""
    out: dict[str, int] = defaultdict(int)
    for m in maps:
        for key, value in m.items():
            out[key] += value
    return dict(out)


def merge_queue_stats(items: list[QueueStats]) -> QueueStats:
    """Sum queue depths/counts; max the last-poll timestamp."""
    if not items:
        return QueueStats()
    timestamps = [q.last_poll_timestamp for q in items if q.last_poll_timestamp]
    return QueueStats(
        queue_depth=_sum_int_maps(q.queue_depth for q in items),
        active_count=_sum_int_maps(q.active_count for q in items),
        total_processed=_sum_int_maps(q.total_processed for q in items),
        dedup_stats=_sum_int_maps(q.dedup_stats for q in items),
        last_poll_timestamp=max(timestamps) if timestamps else None,
        in_flight_count=sum(q.in_flight_count for q in items),
    )


def _merge_stage_stats(items: list[StageStats]) -> StageStats:
    caps = [s.worker_cap for s in items if s.worker_cap is not None]
    return StageStats(
        queued=sum(s.queued for s in items),
        active=sum(s.active for s in items),
        completed_session=sum(s.completed_session for s in items),
        completed_lifetime=sum(s.completed_lifetime for s in items),
        worker_count=sum(s.worker_count for s in items),
        worker_cap=sum(caps) if caps else None,
    )


def merge_pipeline_stats(items: list[PipelineStats]) -> PipelineStats | None:
    """Merge per-stage StageStats, sum throughput, max uptime/timestamp."""
    if not items:
        return None
    stage_keys = {k for p in items for k in p.stages}
    merged_stages = {
        key: _merge_stage_stats([p.stages[key] for p in items if key in p.stages])
        for key in stage_keys
    }
    throughput = ThroughputStats(
        triage=sum(p.throughput.triage for p in items),
        plan=sum(p.throughput.plan for p in items),
        implement=sum(p.throughput.implement for p in items),
        review=sum(p.throughput.review for p in items),
        hitl=sum(p.throughput.hitl for p in items),
    )
    return PipelineStats(
        timestamp=max(p.timestamp for p in items),
        stages=merged_stages,
        queue=merge_queue_stats([p.queue for p in items]),
        throughput=throughput,
        uptime_seconds=max(p.uptime_seconds for p in items),
    )


_LIFETIME_INT_FIELDS = (
    "issues_completed",
    "prs_merged",
    "issues_created",
    "total_quality_fix_rounds",
    "total_ci_fix_rounds",
    "total_hitl_escalations",
    "total_review_request_changes",
    "total_review_approvals",
    "total_reviewer_fixes",
    "total_outcomes_merged",
    "total_outcomes_already_satisfied",
    "total_outcomes_hitl_closed",
    "total_outcomes_hitl_skipped",
    "total_outcomes_failed",
    "total_outcomes_manual_close",
    "total_outcomes_hitl_approved",
    "total_outcomes_verify_pending",
    "total_outcomes_verify_resolved",
)
_LIFETIME_FLOAT_FIELDS = (
    "total_implementation_seconds",
    "total_review_seconds",
    "total_plan_seconds",
    "total_triage_seconds",
)
# Concatenated (NOT summed) so downstream percentile math stays correct.
_LIFETIME_LIST_FIELDS = (
    "plan_durations",
    "implement_durations",
    "review_durations",
    "merge_durations",
)


def merge_lifetime_stats(items: list[LifetimeStats]) -> LifetimeStats:
    """Sum scalar counters, CONCAT duration lists (percentile correctness),
    union ``fired_thresholds``, and merge ``retries_per_stage`` by issue→stage."""
    if not items:
        return LifetimeStats()
    merged: dict[str, Any] = {
        field: sum(getattr(x, field) for x in items) for field in _LIFETIME_INT_FIELDS
    }
    for field in _LIFETIME_FLOAT_FIELDS:
        merged[field] = sum(getattr(x, field) for x in items)
    for field in _LIFETIME_LIST_FIELDS:
        merged[field] = [d for x in items for d in getattr(x, field)]

    seen: set[str] = set()
    fired: list[str] = []
    for x in items:
        for threshold in x.fired_thresholds:
            if threshold not in seen:
                seen.add(threshold)
                fired.append(threshold)
    merged["fired_thresholds"] = fired

    retries: dict[str, dict[str, int]] = {}
    for x in items:
        for issue, stages in x.retries_per_stage.items():
            dest = retries.setdefault(issue, {})
            for stage, count in stages.items():
                dest[stage] = dest.get(stage, 0) + count
    merged["retries_per_stage"] = retries

    return LifetimeStats(**merged)

"""Module-level surface shared by the ``health_monitor_loop`` package.

Split out of the original ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) so the mixin modules have a cycle-free home for
the tunable bounds, adjustment rules, detector thresholds and the two small
value objects (``TrendMetrics``, ``PendingAdjustment``) they all read.
Everything here is re-exported from ``health_monitor_loop/__init__.py`` for
back-compat.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("hydraflow.health_monitor_loop")


TUNABLE_BOUNDS: dict[str, tuple[int, int]] = {
    "max_quality_fix_attempts": (1, 5),
    "agent_timeout": (120, 900),
}

_AdjustmentRule = tuple[str, str, int]  # (condition_key, parameter, step)

ADJUSTMENT_RULES: list[_AdjustmentRule] = [
    ("first_pass_rate_low", "max_quality_fix_attempts", +1),
    ("first_pass_rate_high", "max_quality_fix_attempts", -1),
]

# Thresholds used in condition evaluation
_FIRST_PASS_LOW = 0.2

_FIRST_PASS_HIGH = 0.9

_SURPRISE_HIGH = 0.3

_HITL_HIGH = 0.4

_AVG_SCORE_LOW = 0.4

_STALE_COUNT_HIGH = 5

# HealthMonitor dead-man-switch for TrustFleetSanityLoop (spec §12.1).
# Files a `hydraflow-find` + `sanity-loop-stalled` issue when the sanity
# loop's heartbeat is older than this multiple of its configured interval.
_SANITY_STALL_MULTIPLIER = 3

# Files the same stall when the sanity loop has ticked but reported zero
# workers_scanned for this many consecutive ticks (G5 — activity-based
# health). Catches silent no-op bugs where heartbeat is fresh but the
# loop did no real work.
_SANITY_NOOP_STREAK_THRESHOLD = 3

# Dedup marker recording that the restart-first path already cancelled and
# recreated the sanity loop for the current stall event — the next stall
# tick escalates to an issue instead of restart-thrashing. Cleared with the
# stall dedup key on recovery.
_SANITY_RESTART_KEY = "health_monitor:trust_fleet_sanity:restart-attempted"

# Generic stall sweep across registry loops: a heartbeat older than
# multiplier × interval + cycle_timeout means the loop task is wedged
# outside its watchdog window. The cycle_timeout term keeps a legitimately
# long LLM cycle (heartbeat only refreshes between cycles) from being
# false-restarted.
_WORKER_STALL_MULTIPLIER = 3

# Loops excluded from the generic sweep. trust_fleet_sanity has its own
# §12.1 dead-man-switch above (with G5 no-op detection the generic sweep
# lacks); double coverage would double-restart and double-file.
# health_monitor runs the sweep itself — self-cancelling mid-cycle (stale
# persisted heartbeat after long orchestrator downtime) is harm without
# benefit, and a truly wedged health_monitor can't sweep itself anyway.
_WORKER_STALL_EXCLUDED = frozenset({"trust_fleet_sanity", "health_monitor"})

# Bounded pre-read `git fetch` timeout for the stale-code dead-man-switch
# (#9596). Short and fixed — a single-branch fetch, not a full clone; the
# check must degrade (skip the tick) rather than hang the health-monitor
# cycle when the remote is unreachable.
_STALE_CODE_FETCH_TIMEOUT_SECS = 30.0

# Persistent-error self-repair actuator (#10140, follow-up to #9854's
# read-only health harness). A registry loop whose heartbeat reports
# `error` for this many CONSECUTIVE health_monitor ticks either gets a
# known auto-repair applied or one deduped `hydraflow-find` issue naming
# it filed — the actuator half of the harness, so a repeatedly-failing
# loop self-heals (or is at least surfaced) instead of waiting for a human
# to eyeball the dashboard. Mirrors `_SANITY_NOOP_STREAK_THRESHOLD`'s
# per-tick (not per-underlying-cycle) counting convention: simple, already
# proven in this file, and testable without needing to fake a target
# loop's own cycle cadence.
_ERROR_STREAK_THRESHOLD = 3

# Loops excluded from persistent-error actuation. health_monitor cannot
# meaningfully self-diagnose (mirrors `_WORKER_STALL_EXCLUDED`);
# trust_fleet_sanity already has its own `tick_error_ratio` anomaly
# detector (spec §12.1) for this exact failure class (a loop that ticks
# but keeps failing) — double coverage would double-file.
_PERSISTENT_ERROR_EXCLUDED = frozenset({"trust_fleet_sanity", "health_monitor"})

# RollupIssueManager namespace for the persistent-error actuator's
# generic (unknown-pattern) issue-filing fallback.
_PERSISTENT_ERROR_NAMESPACE = "health_monitor_persistent_error"


class TrendMetrics:
    """Computed health trend metrics for one monitor cycle."""

    def __init__(
        self,
        first_pass_rate: float,
        avg_memory_score: float,
        surprise_rate: float,
        hitl_escalation_rate: float,
        stale_item_count: int,
        total_outcomes: int,
    ) -> None:
        self.first_pass_rate = first_pass_rate
        self.avg_memory_score = avg_memory_score
        self.surprise_rate = surprise_rate
        self.hitl_escalation_rate = hitl_escalation_rate
        self.stale_item_count = stale_item_count
        self.total_outcomes = total_outcomes

    def active_conditions(self) -> list[str]:
        """Return a list of active condition keys for adjustment rule matching."""
        conditions: list[str] = []
        if self.first_pass_rate < _FIRST_PASS_LOW:
            conditions.append("first_pass_rate_low")
        if self.first_pass_rate > _FIRST_PASS_HIGH:
            conditions.append("first_pass_rate_high")
        return conditions


class PendingAdjustment:
    """Tracks a single applied auto-adjustment awaiting outcome verification."""

    def __init__(
        self,
        decision_id: str,
        parameter: str,
        before: int,
        after: int,
        metric_name: str,
        metric_value: float,
        outcomes_at_adjustment: int,
    ) -> None:
        self.decision_id = decision_id
        self.parameter = parameter
        self.before = before
        self.after = after
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.outcomes_at_adjustment = outcomes_at_adjustment

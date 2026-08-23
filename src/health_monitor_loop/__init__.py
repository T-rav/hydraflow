"""Back-compat re-exports for the ``health_monitor_loop`` package.

The original ``src/health_monitor_loop.py`` (2236 lines / a 1506-LOC,
36-method ``HealthMonitorLoop``) was split into this package for mass
discipline (Refs #11547), the same shape ``review_phase/`` and
``implement_phase/`` already use. All existing imports keep working::

    from health_monitor_loop import HealthMonitorLoop      # still works
    from health_monitor_loop import compute_trend_metrics  # still works
    import health_monitor_loop                             # still works

Layout:
  * ``_common.py``    — tunable bounds, the adjustment rule table, the
    detector thresholds, and the ``TrendMetrics`` / ``PendingAdjustment``
    value objects every slice reads.
  * ``_decisions.py`` — the hash-chained ``decisions.jsonl`` audit trail.
  * ``_trends.py``    — ``compute_trend_metrics`` over the outcome trails.
  * ``_loop.py``      — the ``HealthMonitorLoop`` class: construction, the
    fast-tick ``_do_work`` cycle and the heavy-pass cadence gate.
  * ``_heavy.py``     — the heavy pass and the ingestion / auto-file /
    verification / cross-project cycles it fans out to.
  * ``_adjust.py``    — bounded parameter auto-adjustment and its delayed
    outcome verification.
  * ``_hitl.py``      — HITL recommendation filing for out-of-range
    conditions.
  * ``_vitals.py``    — the ADR-0133 fleet reading and its Sentry metrics.
  * ``_stall.py``     — the ADR-0046 dead-man-switch, the generic registry
    stall sweep, and the ADR-0106 event-loop freeze marker.
  * ``_freshness.py`` — wiki-freshness and stale-code detectors plus the
    shared recovery close.
  * ``_errors.py``    — the #10140 persistent-error self-repair actuator.

Each slice is a mixin ``HealthMonitorLoop`` inherits, so there is exactly ONE
class identity and every ``patch.object(HealthMonitorLoop, ...)`` target still
resolves.

``_do_work`` stays in ``_loop.py`` on purpose: ``test_loop_kill_switch_``
``completeness`` reads the ADR-0049 in-body gate out of the loop class's own
body, and a ``_do_work`` living in a mixin would drop out of that check.

**Patch targets follow their call site.** ``run_subprocess`` /
``get_commits_behind`` are bound in the module that CALLS them, so
``patch("health_monitor_loop.run_subprocess")`` would replace an attribute
here and leave the real binding untouched. They are deliberately NOT
re-exported — patch ``health_monitor_loop._freshness.run_subprocess``
instead, so a stale target fails loudly rather than silently no-opping.
"""

from __future__ import annotations

from ._common import (
    _AVG_SCORE_LOW,
    _ERROR_STREAK_THRESHOLD,
    _FIRST_PASS_HIGH,
    _FIRST_PASS_LOW,
    _HITL_HIGH,
    _PERSISTENT_ERROR_EXCLUDED,
    _PERSISTENT_ERROR_NAMESPACE,
    _SANITY_NOOP_STREAK_THRESHOLD,
    _SANITY_RESTART_KEY,
    _SANITY_STALL_MULTIPLIER,
    _STALE_CODE_FETCH_TIMEOUT_SECS,
    _STALE_COUNT_HIGH,
    _SURPRISE_HIGH,
    _WORKER_STALL_EXCLUDED,
    _WORKER_STALL_MULTIPLIER,
    ADJUSTMENT_RULES,
    TUNABLE_BOUNDS,
    PendingAdjustment,
    TrendMetrics,
    _AdjustmentRule,
)
from ._decisions import (
    AuditChain,
    _load_decisions,
    _next_decision_id,
    _update_decision,
    _write_decision,
)
from ._loop import HealthMonitorLoop
from ._trends import compute_trend_metrics

__all__ = [
    "ADJUSTMENT_RULES",
    "TUNABLE_BOUNDS",
    "AuditChain",
    "HealthMonitorLoop",
    "PendingAdjustment",
    "TrendMetrics",
    "_AVG_SCORE_LOW",
    "_AdjustmentRule",
    "_ERROR_STREAK_THRESHOLD",
    "_FIRST_PASS_HIGH",
    "_FIRST_PASS_LOW",
    "_HITL_HIGH",
    "_PERSISTENT_ERROR_EXCLUDED",
    "_PERSISTENT_ERROR_NAMESPACE",
    "_SANITY_NOOP_STREAK_THRESHOLD",
    "_SANITY_RESTART_KEY",
    "_SANITY_STALL_MULTIPLIER",
    "_STALE_CODE_FETCH_TIMEOUT_SECS",
    "_STALE_COUNT_HIGH",
    "_SURPRISE_HIGH",
    "_WORKER_STALL_EXCLUDED",
    "_WORKER_STALL_MULTIPLIER",
    "_load_decisions",
    "_next_decision_id",
    "_update_decision",
    "_write_decision",
    "compute_trend_metrics",
]

"""Five pure anomaly-detector functions for TrustFleetSanityLoop (spec §12.1).

Each detector is a pure function that accepts a normalized metric dict
and returns ``(breached: bool, details: dict)``. No side effects, no
subprocess, no I/O (the cost-spike detector calls the passed reader
module's functions but the reader itself is injected — absent-reader
is a first-class *input*, not a runtime import failure). This makes
unit tests trivial and keeps the loop class focused on orchestration.

Threshold comparisons are ``>=`` per sibling-plan lock. Zero-
denominator paths return ``(False, {"status": "insufficient_data"})``
rather than raising — a fresh install shouldn't escalate the moment it
boots.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("hydraflow.trust_fleet_anomaly_detectors")


# Spec §12.2 — exactly the nine trust loops watched by the sanity loop.
# A new trust-loop's introduction PR appends its worker name here in
# its five-checkpoint-wiring task (spec §12.1 "Watched workers set").
TRUST_LOOP_WORKERS: tuple[str, ...] = (
    "corpus_learning",
    "contract_refresh",
    "staging_bisect",
    "principles_audit",
    "flake_tracker",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "wiki_rot_detector",
)


def detect_issues_per_hour(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: int,
) -> tuple[bool, dict[str, Any]]:
    """`issues_filed_hour >= threshold` -> breach (spec §12.1 bullet 1)."""
    filed = int(metrics.get("issues_filed_hour", 0))
    if filed >= threshold:
        return True, {
            "worker": worker,
            "issues_per_hour": filed,
            "threshold": threshold,
        }
    return False, {
        "worker": worker,
        "issues_per_hour": filed,
        "threshold": threshold,
    }


def detect_repair_ratio(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """`failed / repaired >= threshold` over 24h -> breach (spec §12.1 bullet 2)."""
    repaired = int(metrics.get("repaired_day", 0))
    failed = int(metrics.get("failed_day", 0))
    if repaired == 0 and failed == 0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "repaired": 0,
            "failed": 0,
        }
    if repaired == 0:
        # No successes + >=1 failure — can't compute a finite ratio.
        # Escalate conservatively; operator decides if signal is real.
        return True, {
            "worker": worker,
            "status": "no_successes",
            "repaired": 0,
            "failed": failed,
            "threshold": threshold,
        }
    ratio = failed / repaired
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "ratio": ratio,
        "repaired": repaired,
        "failed": failed,
        "threshold": threshold,
    }


def detect_tick_error_ratio(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """`ticks_errored / ticks_total >= threshold` over 24h (spec §12.1 bullet 3)."""
    total = int(metrics.get("ticks_total", 0))
    errored = int(metrics.get("ticks_errored", 0))
    if total == 0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "ticks_total": 0,
        }
    ratio = errored / total
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "ratio": ratio,
        "ticks_total": total,
        "ticks_errored": errored,
        "threshold": threshold,
    }


def detect_staleness(
    worker: str,
    *,
    last_run_iso: str | None,
    interval_s: int,
    multiplier: float,
    is_enabled: bool,
    now: datetime,
) -> tuple[bool, dict[str, Any]]:
    """Enabled loop hasn't ticked in > multiplier x interval (spec §12.1 bullet 4).

    A *disabled* loop not ticking is correct — no breach. A loop
    without a heartbeat at all is new / not-yet-run — no breach.
    """
    if not is_enabled:
        return False, {"worker": worker, "status": "disabled"}
    if not last_run_iso:
        return False, {"worker": worker, "status": "no_heartbeat"}
    try:
        last_run = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
    except ValueError:
        return False, {"worker": worker, "status": "bad_heartbeat_iso"}
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    elapsed_s = (now - last_run).total_seconds()
    threshold_s = multiplier * interval_s
    breached = elapsed_s >= threshold_s
    return breached, {
        "worker": worker,
        "elapsed_s": int(elapsed_s),
        "interval_s": interval_s,
        "multiplier": multiplier,
        "threshold_s": int(threshold_s),
        "last_run_iso": last_run_iso,
    }


def detect_cost_spike(
    worker: str,
    *,
    reader: Any | None,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """Current-day cost >= threshold x 30-day median (spec §12.1 bullet 5).

    ``reader`` is a module-like object exposing
    ``get_loop_cost_today(worker) -> float`` and
    ``get_loop_cost_30d_median(worker) -> float``. When ``None``
    (reader absent) or raises, the detector returns no-breach with a
    status tag — spec tolerates the §4.11 module being unbuilt.
    """
    if reader is None:
        return False, {"worker": worker, "status": "cost_reader_unavailable"}
    try:
        today = float(reader.get_loop_cost_today(worker))
        median = float(reader.get_loop_cost_30d_median(worker))
    except Exception as exc:  # noqa: BLE001
        logger.debug("cost reader failed for %s: %s", worker, exc, exc_info=True)
        return False, {"worker": worker, "status": "reader_error"}
    if median <= 0.0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "today_usd": today,
            "median_usd": median,
        }
    ratio = today / median
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "today_usd": today,
        "median_usd": median,
        "ratio": ratio,
        "threshold": threshold,
    }

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

from models import Severity

logger = logging.getLogger("hydraflow.trust_fleet_anomaly_detectors")


# Diagnosed-severity values (``Severity.value``) that count as "low-severity"
# for the HITL-composition signal (#10310). P4/Housekeeping is the canonical
# mis-scope: auto-filed housekeeping that should never have reached a human
# judgment fork. Kept as a frozenset so a future PR can widen it (e.g. add
# P3 wiring) via config without touching the detector.
LOW_SEVERITY_VALUES: frozenset[str] = frozenset({Severity.P4_HOUSEKEEPING.value})


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


# Per-loop BACKGROUND_WORKER_STATUS detail keys whose count is a *repair
# success* — a unit of work the loop completed (resolved a flake, refreshed a
# cassette, merged/reverted a bad SHA, synthesized a corpus case, updated a
# fake). ``detect_repair_ratio`` compares 24h ``failed`` against the sum of
# these. Historically the collector and the /api/trust/fleet route only read a
# literal ``repaired`` key that NO production trust loop emits, so
# ``repaired_day`` / ``repair_successes_total`` were permanently 0 and the
# detector could only ever return ``no_successes`` — root cause B of #9458. The
# literal ``repaired`` key is kept first for forward compatibility and for
# tests/scenarios that emit it directly.
REPAIRED_SUCCESS_KEYS: tuple[str, ...] = (
    "repaired",  # generic / scenario-emitted
    "resolved",  # flake_tracker, skill_prompt_eval
    "refreshed",  # contract_refresh
    "updated",  # fake_coverage_auditor
    "merged",  # staging_bisect
    "reverted",  # staging_bisect
    "cases_filed",  # corpus_learning
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
    min_sample: int = 1,
) -> tuple[bool, dict[str, Any]]:
    """`failed / repaired >= threshold` over 24h -> breach (spec §12.1 bullet 2).

    ``min_sample`` is the floor on the 24h ``failed`` count required before the
    zero-success (`no_successes`) branch escalates. A single failure with no
    recorded successes is not enough signal to page a human — below the floor
    the detector returns no breach with ``status="insufficient_data"``,
    mirroring the zero/zero guard (false-positive guard, issue #9458).
    """
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
        if failed < min_sample:
            # Too few failures to escalate a zero-success loop — a routine
            # one-off failure shouldn't page a human (issue #9458).
            return False, {
                "worker": worker,
                "status": "insufficient_data",
                "repaired": 0,
                "failed": failed,
                "min_sample": min_sample,
            }
        # No successes + enough failures to clear the floor — can't compute a
        # finite ratio. Escalate conservatively; operator decides if real.
        return True, {
            "worker": worker,
            "status": "no_successes",
            "repaired": 0,
            "failed": failed,
            "threshold": threshold,
            "min_sample": min_sample,
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
    min_sample: int = 1,
) -> tuple[bool, dict[str, Any]]:
    """`ticks_errored / ticks_total >= threshold` over 24h (spec §12.1 bullet 3).

    ``min_sample`` is the floor on the 24h ``ticks_total`` count required
    before the ratio can breach. Low-cadence loops (e.g. weekly ticks) can hit
    a high error *ratio* off a single transient failure; below the floor the
    detector returns no breach with ``status="insufficient_data"``, mirroring
    ``detect_repair_ratio``'s min-sample guard (false-positive guard, issue
    #9811).
    """
    total = int(metrics.get("ticks_total", 0))
    errored = int(metrics.get("ticks_errored", 0))
    if total == 0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "ticks_total": 0,
        }
    if total < min_sample:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "ticks_total": total,
            "ticks_errored": errored,
            "min_sample": min_sample,
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
    max_cycle_s: int = 0,
    boot_time: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Enabled loop idle past its expected-idle window (spec §12.1 bullet 4).

    The breach threshold is ``max(multiplier * interval_s, max_cycle_s)`` (#10236).
    ``interval_s`` is the watched worker's *poll* cadence and, for most trust
    loops (hours-to-days intervals doing bounded fast work), ``multiplier *
    interval_s`` sits far above any legitimate single-tick duration. But a loop
    whose poll interval is short by design yet whose expected *cycle duration*
    is long — ``staging_bisect`` polls ``last_rc_red_sha`` every 600s but a
    confirmed red synchronously runs flake probes plus a full ``git bisect``,
    each capped at ``staging_bisect_runtime_cap_seconds``, inside the per-cycle
    watchdog — would otherwise be false-flagged stale mid-cycle (#10234).
    ``max_cycle_s`` is that per-worker "expected max single-cycle duration"
    floor (the loop's own watchdog / cycle-timeout bound), decoupled from poll
    cadence; the default ``0`` leaves the poll-based threshold unchanged.

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
    # Boot grace (#11119): heartbeats PERSIST across factory downtime, so on
    # a cold boot every loop's last_run reads hours-to-days old and the whole
    # fleet false-flags stale before any loop has had a chance to tick.
    # Staleness is therefore measured from the LATER of last_run and the
    # orchestrator boot — after a boot, a loop gets its full threshold window
    # before being judged.
    reference = last_run
    boot_governed = False
    if boot_time is not None and boot_time > last_run:
        reference = boot_time
        boot_governed = True
    elapsed_s = (now - reference).total_seconds()
    threshold_s = max(multiplier * interval_s, float(max_cycle_s))
    breached = elapsed_s >= threshold_s
    details = {
        "worker": worker,
        "elapsed_s": int(elapsed_s),
        "interval_s": interval_s,
        "multiplier": multiplier,
        "max_cycle_s": max_cycle_s,
        "threshold_s": int(threshold_s),
        "last_run_iso": last_run_iso,
    }
    if boot_governed and not breached:
        # Distinguishable in the rollup: within-grace is not "healthy tick",
        # it is "not judged yet" (#11121's warmup-vs-healthy distinction).
        details["status"] = "boot_grace"
    return breached, details


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


def detect_hitl_composition(
    hitl_items: list[dict[str, Any]],
    *,
    threshold: int,
    low_severities: frozenset[str] = LOW_SEVERITY_VALUES,
) -> tuple[bool, dict[str, Any]]:
    """Flag when the open HITL queue is dominated by low-severity items (#10310).

    A fleet-wide (not per-worker) signal: when the human-in-the-loop queue
    fills with P4/housekeeping items, the pipeline is *mis-scoping* auto-filed
    issues into human-judgment forks — over-escalating low-value work a human
    should never have to triage (#10292). This is the backstop for the next
    unforeseen mis-scope class beyond the targeted memory-backlog fix.

    Each item is a normalized dict::

        {"number": int, "severity": str | None, "housekeeping": bool}

    An item counts as *low-severity* when its diagnosed severity value is in
    *low_severities* (P4/Housekeeping) OR it carries a housekeeping label
    (``housekeeping=True``, e.g. ``hydraflow-memory-backlog``). Breach when the
    low-severity count is ``>= threshold`` (``>=`` per sibling-plan lock). An
    empty queue returns ``insufficient_data`` — a fresh/quiet queue must never
    escalate.
    """
    total = len(hitl_items)
    if total == 0:
        return False, {
            "status": "insufficient_data",
            "total": 0,
            "low_severity": 0,
            "threshold": threshold,
        }
    low_numbers: list[int] = []
    for item in hitl_items:
        severity = item.get("severity")
        is_low = (isinstance(severity, str) and severity in low_severities) or bool(
            item.get("housekeeping")
        )
        if is_low:
            number = item.get("number")
            if isinstance(number, int):
                low_numbers.append(number)
    low = len(low_numbers)
    breached = low >= threshold
    return breached, {
        "total": total,
        "low_severity": low,
        "fraction": round(low / total, 3),
        "threshold": threshold,
        "issues": sorted(low_numbers),
    }

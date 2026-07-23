"""Regression for #10236: staleness detector conflates poll cadence with cycle duration.

``TrustFleetSanityLoop.detect_staleness`` computed its breach threshold as
``multiplier * interval_s`` where ``interval_s`` is the watched worker's *poll*
interval. For a loop like ``staging_bisect`` whose poll interval is short
(``staging_bisect_interval`` default 600s, purely a cheap ``last_rc_red_sha``
watchdog poll) but whose expected *cycle duration* is long (a confirmed red
SHA synchronously runs flake-probe subprocesses plus a full ``git bisect``,
each capped at ``staging_bisect_runtime_cap_seconds`` = 2700s, all inside the
7200s per-cycle watchdog), ``2.0 * 600 = 1200`` under-estimated the true
expected-idle window. A healthy-but-slow cycle (elapsed 1310s, well inside the
watchdog) was falsely flagged ``staleness`` and paged a human (#10234).

The fix gives ``detect_staleness`` a per-worker "expected max single-cycle
duration" floor (``max_cycle_s``, sourced from ``BGWorkerManager.cycle_timeout``
= the loop's own watchdog bound), decoupled from poll cadence:
``threshold_s = max(multiplier * interval_s, max_cycle_s)``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trust_fleet_anomaly_detectors import detect_staleness


def test_short_interval_long_cycle_loop_not_falsely_stale() -> None:
    """The #10234 false positive: elapsed inside the cycle floor must not breach.

    staging_bisect: interval 600s, multiplier 2.0 (poll-based threshold 1200s),
    watchdog/cycle bound 7200s, elapsed 1310s. Pre-fix this breached
    (1310 >= 1200); with the cycle-duration floor the threshold rises to 7200s
    and a healthy-but-slow cycle no longer pages.
    """
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=1310)).isoformat()
    breached, details = detect_staleness(
        "staging_bisect",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        max_cycle_s=7200,
        is_enabled=True,
        now=now,
    )
    assert breached is False
    # Threshold is driven by the cycle-duration floor, not the poll cadence.
    assert details["threshold_s"] == 7200
    assert details["max_cycle_s"] == 7200


def test_cycle_floor_does_not_suppress_a_genuinely_stalled_loop() -> None:
    """Past the cycle-duration floor a truly-idle enabled loop still breaches."""
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=9000)).isoformat()
    breached, details = detect_staleness(
        "staging_bisect",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        max_cycle_s=7200,
        is_enabled=True,
        now=now,
    )
    assert breached is True
    assert details["threshold_s"] == 7200


def test_poll_threshold_still_wins_when_it_exceeds_the_cycle_floor() -> None:
    """For a long-poll loop the multiplier x interval term still dominates.

    A weekly trust loop (interval 7d) with a tiny cycle bound keeps its
    generous poll-based threshold — the floor is a max(), never a downgrade.
    """
    now = datetime.now(UTC)
    interval_s = 7 * 24 * 3600
    last_run = (now - timedelta(seconds=interval_s)).isoformat()  # 1x interval
    breached, details = detect_staleness(
        "wiki_rot_detector",
        last_run_iso=last_run,
        interval_s=interval_s,
        multiplier=2.0,
        max_cycle_s=7200,
        is_enabled=True,
        now=now,
    )
    assert breached is False
    assert details["threshold_s"] == 2 * interval_s

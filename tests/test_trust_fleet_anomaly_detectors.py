"""Unit tests — one per anomaly detector (spec §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from trust_fleet_anomaly_detectors import (
    TRUST_LOOP_WORKERS,
    detect_cost_spike,
    detect_issues_per_hour,
    detect_repair_ratio,
    detect_staleness,
    detect_tick_error_ratio,
)


def test_trust_loop_workers_contains_nine_spec_workers() -> None:
    """Sanity: the hard-coded watched-worker tuple matches spec §12.2."""
    expected = {
        "corpus_learning",
        "contract_refresh",
        "staging_bisect",
        "principles_audit",
        "flake_tracker",
        "skill_prompt_eval",
        "fake_coverage_auditor",
        "rc_budget",
        "wiki_rot_detector",
    }
    assert set(TRUST_LOOP_WORKERS) == expected


# --- 1. issues-per-hour ---


def test_issues_per_hour_breaches_on_overshoot() -> None:
    metrics = {"issues_filed_hour": 15}
    breached, details = detect_issues_per_hour(
        "ci_monitor",
        metrics,
        threshold=10,
    )
    assert breached is True
    assert details["issues_per_hour"] == 15
    assert details["threshold"] == 10


def test_issues_per_hour_exact_match_breaches() -> None:
    """`>=` comparison (sibling plan lock)."""
    metrics = {"issues_filed_hour": 10}
    breached, _ = detect_issues_per_hour("x", metrics, threshold=10)
    assert breached is True


def test_issues_per_hour_below_does_not_breach() -> None:
    metrics = {"issues_filed_hour": 3}
    breached, _ = detect_issues_per_hour("x", metrics, threshold=10)
    assert breached is False


# --- 2. repair ratio ---


def test_repair_ratio_breaches_when_failures_dominate() -> None:
    metrics = {"repaired_day": 2, "failed_day": 6}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is True
    assert details["ratio"] == pytest.approx(3.0)


def test_repair_ratio_insufficient_data_returns_false() -> None:
    metrics = {"repaired_day": 0, "failed_day": 0}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_repair_ratio_zero_success_with_failures_treated_as_breach() -> None:
    """0 successes + ≥1 failure can't compute a finite ratio safely — the
    sanity loop errs on the side of alerting (operator decides)."""
    metrics = {"repaired_day": 0, "failed_day": 5}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is True
    assert details["status"] == "no_successes"


# --- 3. tick-error ratio ---


def test_tick_error_ratio_breaches_on_high_error_rate() -> None:
    metrics = {"ticks_total": 10, "ticks_errored": 3}
    breached, details = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is True
    assert details["ratio"] == pytest.approx(0.3)


def test_tick_error_ratio_insufficient_data_returns_false() -> None:
    metrics = {"ticks_total": 0, "ticks_errored": 0}
    breached, details = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_tick_error_ratio_at_threshold_breaches() -> None:
    metrics = {"ticks_total": 10, "ticks_errored": 2}
    breached, _ = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is True


# --- 4. staleness ---


def test_staleness_breaches_when_interval_exceeded_and_enabled() -> None:
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=3000)).isoformat()
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        is_enabled=True,
        now=now,
    )
    assert breached is True
    assert details["elapsed_s"] >= 3000
    assert details["threshold_s"] == 1200


def test_staleness_respects_disabled_flag() -> None:
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=999999)).isoformat()
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        is_enabled=False,
        now=now,
    )
    assert breached is False
    assert details["status"] == "disabled"


def test_staleness_no_heartbeat_is_not_a_breach() -> None:
    now = datetime.now(UTC)
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=None,
        interval_s=600,
        multiplier=2.0,
        is_enabled=True,
        now=now,
    )
    assert breached is False
    assert details["status"] == "no_heartbeat"


# --- 5. cost spike ---


def test_cost_spike_breaches_on_overshoot() -> None:
    mod = MagicMock()
    mod.get_loop_cost_today.return_value = 60.0
    mod.get_loop_cost_30d_median.return_value = 10.0
    breached, details = detect_cost_spike(
        "rc_budget",
        reader=mod,
        threshold=5.0,
    )
    assert breached is True
    assert details["today_usd"] == pytest.approx(60.0)
    assert details["median_usd"] == pytest.approx(10.0)
    assert details["ratio"] == pytest.approx(6.0)


def test_cost_spike_absent_reader_returns_no_breach() -> None:
    breached, details = detect_cost_spike("rc_budget", reader=None, threshold=5.0)
    assert breached is False
    assert details["status"] == "cost_reader_unavailable"


def test_cost_spike_zero_median_returns_false() -> None:
    mod = MagicMock()
    mod.get_loop_cost_today.return_value = 5.0
    mod.get_loop_cost_30d_median.return_value = 0.0
    breached, details = detect_cost_spike(
        "rc_budget",
        reader=mod,
        threshold=5.0,
    )
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_cost_spike_reader_exception_returns_false() -> None:
    """A broken cost reader must not crash the sanity loop."""
    mod = MagicMock()
    mod.get_loop_cost_today.side_effect = RuntimeError("boom")
    breached, details = detect_cost_spike(
        "rc_budget",
        reader=mod,
        threshold=5.0,
    )
    assert breached is False
    assert details["status"] == "reader_error"

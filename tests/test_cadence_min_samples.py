"""Tests for ``cadence_min_samples``: per-loop min-samples derived from cadence.

A proposer loop files at most ~one batch per tick, so the achievable sample
ceiling inside a fitness window is roughly ``window / interval``. The helper
caps the configured global minimum at that ceiling (never below the floor) so
a slow loop cannot be locked into permanent INSUFFICIENT_DATA (#9841).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loop_fitness import (
    MIN_SAMPLES_FLOOR,
    Confidence,
    FitnessContext,
    IssueRecord,
    cadence_min_samples,
    proposal_acceptance_fitness,
)

_END = datetime(2026, 7, 20, tzinfo=UTC)

_DAY = 86400


def _ctx(window_days: int, issues: list[IssueRecord] | None = None) -> FitnessContext:
    return FitnessContext(
        window_start=_END - timedelta(days=window_days),
        window_end=_END,
        issues=issues or [],
    )


def test_fast_loop_keeps_configured_min() -> None:
    # Hourly loop, 30-day window: 720 achievable ticks >> configured 5.
    assert cadence_min_samples(_ctx(30), interval_seconds=3600, configured_min=5) == 5


def test_daily_loop_week_window_caps_at_achievable() -> None:
    # Daily loop, 7-day window: only 7 samples are achievable, so a configured
    # minimum of 20 must not be required — it would be mathematically unreachable.
    assert cadence_min_samples(_ctx(7), interval_seconds=_DAY, configured_min=20) == 7


def test_slow_loop_capped_but_never_below_floor() -> None:
    # Weekly loop, 30-day window: 4 achievable ticks -> cap at 4.
    assert (
        cadence_min_samples(_ctx(30), interval_seconds=7 * _DAY, configured_min=20) == 4
    )
    # Monthly loop, 7-day window: 0 achievable ticks -> floor keeps a minimum.
    assert (
        cadence_min_samples(_ctx(7), interval_seconds=30 * _DAY, configured_min=20)
        == MIN_SAMPLES_FLOOR
    )


def test_explicit_low_configured_min_is_honored() -> None:
    # An operator who explicitly sets min below the floor keeps that authority.
    assert cadence_min_samples(_ctx(30), interval_seconds=_DAY, configured_min=2) == 2


def test_non_positive_interval_falls_back_to_configured_min() -> None:
    assert cadence_min_samples(_ctx(30), interval_seconds=0, configured_min=5) == 5
    assert cadence_min_samples(_ctx(30), interval_seconds=-1, configured_min=5) == 5


def test_daily_loop_with_week_of_samples_scores_for_real() -> None:
    # The #9841 acceptance shape: a daily-cadence loop that ran for a week and
    # filed one proposal per day must produce a REAL score, not
    # insufficient_data.
    issues = [
        IssueRecord(
            number=i,
            labels=["edge-proposal"],
            is_pr=True,
            state="closed" if i < 4 else "open",
            merged=i < 4,
            created_at=_END - timedelta(days=6) + timedelta(days=i),
        )
        for i in range(7)
    ]
    ctx = _ctx(7, issues)
    fit = proposal_acceptance_fitness(
        ctx,
        worker_name="edge_proposer",
        label="edge-proposal",
        min_samples=cadence_min_samples(ctx, interval_seconds=_DAY, configured_min=5),
    )
    assert fit.confidence is Confidence.OK
    assert fit.score == 4 / 7
    assert fit.sample_count == 7

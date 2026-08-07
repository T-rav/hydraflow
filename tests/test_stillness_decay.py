"""Unit tests for the quiet-week decay curve (#10822)."""

from __future__ import annotations

from stillness.decay import (
    DailyActivity,
    DecayVerdict,
    SignalClass,
    fit_decay,
)


def _series(
    self_counts: list[int], external_counts: list[int] | None = None
) -> list[DailyActivity]:
    ext = external_counts or [0] * len(self_counts)
    return [
        DailyActivity(day_index=i, self_originated=s, external=e)
        for i, (s, e) in enumerate(zip(self_counts, ext, strict=True))
    ]


def test_signal_class_values() -> None:
    assert SignalClass.SELF_ORIGINATED == "self_originated"
    assert SignalClass.EXTERNAL == "external"


def test_daily_total_sums_both_classes() -> None:
    assert DailyActivity(0, self_originated=7, external=3).total == 10


def test_activity_that_decays_to_the_floor_is_healthy() -> None:
    # Self-originated churn falling toward the sensing floor, no external input.
    fit = fit_decay(_series([18, 10, 5, 3, 2, 1, 1]), floor=1.0)
    assert fit.verdict is DecayVerdict.DECAYING
    assert fit.decay_rate > 0.15  # a real decay, not noise
    assert fit.self_sustaining is False


def test_self_sustaining_churn_with_no_external_input_is_hunting() -> None:
    # Flat self-originated activity well above the floor, zero external input —
    # the factory is its own disturbance source. The formal definition of hunting.
    fit = fit_decay(_series([10, 11, 9, 10, 12, 10, 11]), floor=1.0)
    assert fit.verdict is DecayVerdict.HUNTING
    assert fit.self_sustaining is True
    assert fit.decay_rate < 0.15


def test_flat_activity_with_external_input_is_not_hunting() -> None:
    # Same non-decaying activity, but genuine external disturbance is present, so
    # it is NOT self-sustaining — the freeze's excuse for continued activity.
    fit = fit_decay(
        _series([8, 9, 7, 8, 10, 8, 9], external_counts=[2, 2, 2, 2, 2, 2, 2]),
        floor=1.0,
    )
    assert fit.self_sustaining is False
    assert fit.verdict is DecayVerdict.INCONCLUSIVE


def test_too_short_a_window_is_insufficient_data() -> None:
    fit = fit_decay(_series([10, 5]), floor=1.0)
    assert fit.verdict is DecayVerdict.INSUFFICIENT_DATA
    assert fit.n_days == 2


def test_series_is_sorted_by_day_before_fitting() -> None:
    # Out-of-order days must not fool the fit — a decaying series shuffled is
    # still decaying.
    ordered = _series([18, 10, 5, 3, 2, 1, 1])
    shuffled = [ordered[i] for i in (3, 0, 6, 1, 5, 2, 4)]
    assert fit_decay(shuffled, floor=1.0).verdict is DecayVerdict.DECAYING

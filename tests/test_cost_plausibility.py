"""Unit tests for the cost-plausibility guard (#10775)."""

from __future__ import annotations

from cost_plausibility import (
    DEFAULT_MAX_RATE_MULTIPLE,
    CostPlausibilityAnomaly,
    check_cost_plausibility,
)
from model_pricing import ModelRate

_RATE = ModelRate(
    input_cost_per_million=1.40,
    output_cost_per_million=4.40,
    cache_write_cost_per_million=1.40,
    cache_read_cost_per_million=0.26,
)


def test_peak_rate_is_the_largest_of_the_four_rates() -> None:
    assert _RATE.peak_rate_per_million() == 4.40


def test_returns_none_when_effective_rate_within_ceiling() -> None:
    # $1/M effective is well under 3 x peak ($4.40/M).
    assert (
        check_cost_plausibility(
            model="m", cost_usd=0.001, total_tokens=1_000, rate=_RATE, threshold=3.0
        )
        is None
    )


def test_flags_when_effective_rate_exceeds_k_times_peak() -> None:
    # $100/M effective over 1,000 tokens vastly exceeds 3 x $4.40/M.
    anomaly = check_cost_plausibility(
        model="m", cost_usd=0.10, total_tokens=1_000, rate=_RATE, threshold=3.0
    )
    assert isinstance(anomaly, CostPlausibilityAnomaly)
    assert anomaly.effective_rate_per_million == 100.0
    assert anomaly.peak_rate_per_million == 4.40
    assert anomaly.ratio == 100.0 / 4.40
    assert anomaly.threshold == 3.0


def test_threshold_k_is_respected() -> None:
    # Effective rate is 5 x peak: flagged at K=3, not flagged at K=6.
    kwargs = {
        "model": "m",
        "cost_usd": 4.40 * 5 * 1_000 / 1_000_000,
        "total_tokens": 1_000,
        "rate": _RATE,
    }
    assert check_cost_plausibility(**kwargs, threshold=3.0) is not None
    assert check_cost_plausibility(**kwargs, threshold=6.0) is None


def test_just_below_ceiling_passes_just_above_flags() -> None:
    at = 3.0 * 4.40 * 1_000 / 1_000_000  # exactly K x peak over 1,000 tokens
    assert (
        check_cost_plausibility(
            model="m", cost_usd=at * 0.99, total_tokens=1_000, rate=_RATE, threshold=3.0
        )
        is None
    )
    assert (
        check_cost_plausibility(
            model="m", cost_usd=at * 1.01, total_tokens=1_000, rate=_RATE, threshold=3.0
        )
        is not None
    )


def test_returns_none_for_unpriced_model() -> None:
    assert (
        check_cost_plausibility(
            model="m", cost_usd=999.0, total_tokens=1, rate=None, threshold=3.0
        )
        is None
    )


def test_returns_none_for_zero_or_negative_inputs() -> None:
    assert (
        check_cost_plausibility(
            model="m", cost_usd=0.0, total_tokens=1_000, rate=_RATE, threshold=3.0
        )
        is None
    )
    assert (
        check_cost_plausibility(
            model="m", cost_usd=1.0, total_tokens=0, rate=_RATE, threshold=3.0
        )
        is None
    )
    assert (
        check_cost_plausibility(
            model="m", cost_usd=1.0, total_tokens=1_000, rate=_RATE, threshold=0.0
        )
        is None
    )


def test_returns_none_when_peak_rate_is_zero() -> None:
    zero_rate = ModelRate(
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
        cache_write_cost_per_million=0.0,
        cache_read_cost_per_million=0.0,
    )
    assert (
        check_cost_plausibility(
            model="m", cost_usd=1.0, total_tokens=1_000, rate=zero_rate, threshold=3.0
        )
        is None
    )


def test_default_threshold_is_three() -> None:
    assert DEFAULT_MAX_RATE_MULTIPLE == 3.0

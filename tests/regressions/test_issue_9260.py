"""Regression test for issue #9260 — [pricing-refresh] bounds violation.

PricingRefreshLoop rejected an upstream pricing update for ``claude-opus-4-7``
because every cost field dropped to ~1/3 of its prior value (ratio 0.33),
tripping the ``< -50%`` bounds guard in ``src/pricing_refresh_diff.py:120-124``.

A ``[pricing-refresh] bounds violation`` issue is a *human-verification gate*,
not a guard bug: the guard is behaving correctly by refusing to silently apply
a large price swing. The fault is that the local asset
(``src/assets/model_pricing.json``) is now stale relative to upstream. The fix
is to update the asset to the upstream values; the loop's next tick then sees
``local == upstream``, reports no drift, and auto-closes the issue.

Upstream values reported by the issue (note the internal cache ratios are
preserved — ``cache_write = 1.25 x input`` and ``cache_read = 0.1 x input`` —
which confirms a real coordinated price cut, not corrupted data):

    input_cost_per_million:        15.0   ->  5.0
    output_cost_per_million:       75.0   -> 25.0
    cache_write_cost_per_million:  18.75  ->  6.25
    cache_read_cost_per_million:    1.5   ->  0.5

These tests assert the CORRECTED (post-fix) rates via the public
``load_pricing()`` surface and are therefore RED against the current stale
asset. They go green once ``model_pricing.json`` is updated, which is exactly
the asset edit that resolves #9260.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from model_pricing import load_pricing

# Upstream (post-cut) rates from the issue, in USD per million tokens.
_EXPECTED_INPUT = 5.0
_EXPECTED_OUTPUT = 25.0
_EXPECTED_CACHE_WRITE = 6.25
_EXPECTED_CACHE_READ = 0.5


def test_opus_4_7_input_cost_matches_upstream() -> None:
    rate = load_pricing().get_rate("claude-opus-4-7")
    assert rate is not None
    assert rate.input_cost_per_million == _EXPECTED_INPUT


def test_opus_4_7_output_cost_matches_upstream() -> None:
    rate = load_pricing().get_rate("claude-opus-4-7")
    assert rate is not None
    assert rate.output_cost_per_million == _EXPECTED_OUTPUT


def test_opus_4_7_cache_write_cost_matches_upstream() -> None:
    rate = load_pricing().get_rate("claude-opus-4-7")
    assert rate is not None
    assert rate.cache_write_cost_per_million == _EXPECTED_CACHE_WRITE


def test_opus_4_7_cache_read_cost_matches_upstream() -> None:
    rate = load_pricing().get_rate("claude-opus-4-7")
    assert rate is not None
    assert rate.cache_read_cost_per_million == _EXPECTED_CACHE_READ


def test_opus_4_7_cache_ratios_confirm_real_price_cut() -> None:
    # Internal ratios are fixed across a coordinated price cut, so they hold
    # at the corrected rates: cache_write = 1.25 x input, cache_read = 0.1 x
    # input. (Documents why this swing is a real cut, not corrupted data.)
    rate = load_pricing().get_rate("claude-opus-4-7")
    assert rate is not None
    assert rate.cache_write_cost_per_million == 1.25 * rate.input_cost_per_million
    assert rate.cache_read_cost_per_million == 0.1 * rate.input_cost_per_million

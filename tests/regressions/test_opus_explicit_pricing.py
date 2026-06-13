"""Regression test: claude-opus-4-6 and claude-opus-4-8 must resolve via explicit entries.

Previously both models silently fell through to the fuzzy "opus" alias and returned
claude-opus-4-7's $15/$75 rates. This file locks in exact $5/$25 resolution so any
future JSON drift triggers an immediate test failure.
"""

from __future__ import annotations

from model_pricing import load_pricing


def test_claude_opus_4_8_resolves_to_explicit_5_dollar_entry():
    table = load_pricing()
    rate = table.get_rate("claude-opus-4-8")
    assert rate is not None, (
        "claude-opus-4-8 must have an explicit entry in model_pricing.json"
    )
    assert rate.input_cost_per_million == 5.0, (
        f"Expected input=5.0, got {rate.input_cost_per_million} — "
        "claude-opus-4-8 is resolving via fuzzy fallback to a wrong entry"
    )
    assert rate.output_cost_per_million == 25.0
    assert rate.cache_write_cost_per_million == 6.25
    assert rate.cache_read_cost_per_million == 0.50


def test_claude_opus_4_6_resolves_to_explicit_5_dollar_entry():
    table = load_pricing()
    rate = table.get_rate("claude-opus-4-6")
    assert rate is not None, (
        "claude-opus-4-6 must have an explicit entry in model_pricing.json"
    )
    assert rate.input_cost_per_million == 5.0, (
        f"Expected input=5.0, got {rate.input_cost_per_million} — "
        "claude-opus-4-6 is resolving via fuzzy fallback to a wrong entry"
    )
    assert rate.output_cost_per_million == 25.0
    assert rate.cache_write_cost_per_million == 6.25
    assert rate.cache_read_cost_per_million == 0.50

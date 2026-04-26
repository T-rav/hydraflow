"""Pure-function tests for pricing_refresh_diff module."""

from __future__ import annotations

import pytest

from pricing_refresh_diff import (
    filter_anthropic_entries,
    map_litellm_to_local_costs,
    normalize_litellm_key,
)


def test_normalize_strips_bedrock_prefix() -> None:
    assert (
        normalize_litellm_key("anthropic.claude-haiku-4-5-20251001-v1:0")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_strips_bedrock_at_suffix() -> None:
    assert (
        normalize_litellm_key("anthropic.claude-haiku-4-5@20251001")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_passthrough_canonical() -> None:
    assert (
        normalize_litellm_key("claude-haiku-4-5-20251001")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_strips_only_v1_zero() -> None:
    # Other v-suffixes preserved as-is — only v1:0 is the Bedrock convention.
    assert normalize_litellm_key("claude-future-v2:1") == "claude-future-v2:1"


def test_filter_keeps_only_anthropic_provider() -> None:
    raw = {
        "claude-haiku-4-5": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
        },
        "gpt-4": {"litellm_provider": "openai", "input_cost_per_token": 1e-5},
        "anthropic.claude-3-haiku": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-7,
        },
    }
    out = filter_anthropic_entries(raw)
    assert set(out.keys()) == {"claude-haiku-4-5", "claude-3-haiku"}


def test_filter_skips_entries_without_provider_field() -> None:
    raw = {
        "claude-thing": {"litellm_provider": "anthropic", "input_cost_per_token": 1e-6},
        "missing-provider": {"input_cost_per_token": 1e-6},
    }
    out = filter_anthropic_entries(raw)
    assert set(out.keys()) == {"claude-thing"}


def test_map_per_token_to_per_million() -> None:
    upstream = {
        "input_cost_per_token": 1e-6,  # 1.00 / M
        "output_cost_per_token": 5e-6,  # 5.00 / M
        "cache_creation_input_token_cost": 1.25e-6,  # 1.25 / M
        "cache_read_input_token_cost": 1e-7,  # 0.10 / M
    }
    out = map_litellm_to_local_costs(upstream)
    assert out == {
        "input_cost_per_million": 1.00,
        "output_cost_per_million": 5.00,
        "cache_write_cost_per_million": 1.25,
        "cache_read_cost_per_million": 0.10,
    }


def test_map_handles_missing_cache_fields_as_zero() -> None:
    """Some legacy entries lack cache fields entirely."""
    upstream = {
        "input_cost_per_token": 3e-6,
        "output_cost_per_token": 15e-6,
    }
    out = map_litellm_to_local_costs(upstream)
    assert out["cache_write_cost_per_million"] == 0.0
    assert out["cache_read_cost_per_million"] == 0.0
    assert out["input_cost_per_million"] == 3.00


def test_map_raises_on_missing_required_field() -> None:
    """input_cost_per_token and output_cost_per_token are required."""
    with pytest.raises(KeyError):
        map_litellm_to_local_costs({"output_cost_per_token": 1e-6})
    with pytest.raises(KeyError):
        map_litellm_to_local_costs({"input_cost_per_token": 1e-6})


def test_map_rounds_to_six_decimals() -> None:
    """Floating-point artifacts shouldn't leak into the JSON output."""
    upstream = {
        "input_cost_per_token": 1e-6 / 3,  # repeating decimal
        "output_cost_per_token": 5e-6,
    }
    out = map_litellm_to_local_costs(upstream)
    # 1e-6 / 3 * 1e6 = 0.333... rounded to 6 decimals = 0.333333
    assert out["input_cost_per_million"] == 0.333333

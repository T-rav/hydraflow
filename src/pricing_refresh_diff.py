"""Pure-function helpers for PricingRefreshLoop.

No IO, no logging, no external state. All functions deterministic and
trivially testable. Importing this module must not trigger any side
effects.
"""

from __future__ import annotations

from typing import Any

_BEDROCK_PREFIX = "anthropic."
_V1_ZERO_SUFFIX = "-v1:0"


def normalize_litellm_key(key: str) -> str:
    """Strip Bedrock-style prefixes/suffixes so a LiteLLM key matches our local naming.

    LiteLLM publishes both bare canonical keys (``claude-haiku-4-5-20251001``)
    and Bedrock-prefixed variants (``anthropic.claude-haiku-4-5-20251001-v1:0``,
    ``anthropic.claude-haiku-4-5@20251001``). All three normalize to the same
    canonical form.
    """
    out = key
    if out.startswith(_BEDROCK_PREFIX):
        out = out[len(_BEDROCK_PREFIX) :]
    # The "@YYYYMMDD" convention is treated as "-YYYYMMDD" for our naming.
    out = out.replace("@", "-")
    if out.endswith(_V1_ZERO_SUFFIX):
        out = out[: -len(_V1_ZERO_SUFFIX)]
    return out


def filter_anthropic_entries(
    raw: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep only entries whose ``litellm_provider`` is ``"anthropic"``.

    Returns a NEW dict keyed by :func:`normalize_litellm_key` of the original.
    Entries without a ``litellm_provider`` field are skipped.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("litellm_provider") != "anthropic":
            continue
        out[normalize_litellm_key(key)] = entry
    return out


def map_litellm_to_local_costs(upstream: dict[str, Any]) -> dict[str, float]:
    """Map LiteLLM per-token costs to our per-million-tokens shape.

    Required upstream keys: ``input_cost_per_token``, ``output_cost_per_token``.
    Cache fields (``cache_creation_input_token_cost``, ``cache_read_input_token_cost``)
    default to 0 when absent. All output values rounded to 6 decimals.

    Raises:
        KeyError: a required field is missing.
    """
    return {
        "input_cost_per_million": round(
            float(upstream["input_cost_per_token"]) * 1e6, 6
        ),
        "output_cost_per_million": round(
            float(upstream["output_cost_per_token"]) * 1e6, 6
        ),
        "cache_write_cost_per_million": round(
            float(upstream.get("cache_creation_input_token_cost", 0.0)) * 1e6, 6
        ),
        "cache_read_cost_per_million": round(
            float(upstream.get("cache_read_input_token_cost", 0.0)) * 1e6, 6
        ),
    }

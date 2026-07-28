"""Regression pins for issue #10761 — z.ai/GLM cost double-counted cached tokens.

The operator saw ``glm-5.2`` ≈ $206 (14.2% of total) on the per-model cost
dashboard while actual z.ai (usage-based) spend was ~$25-35 — a 2-7x
over-report.

Root cause: z.ai / GLM-5.2 reports token usage in **OpenAI style** — its
``usage.prompt_tokens`` **includes** the cached tokens, with the cached subset
reported separately in ``usage.prompt_tokens_details.cached_tokens`` (per z.ai's
context-caching docs). z.ai's Anthropic-compatible endpoint (``/api/anthropic``,
ADR-0110) is consumed by the Claude CLI, so the stream is Claude-format events
and ``stream_parser._ClaudeUsageExtractor`` handles the ``usage`` object.
``_canonical_usage_key`` maps ``prompt_tokens -> input_tokens`` and (via nested
recursion) ``cached_tokens -> cache_read_input_tokens``. ``ModelRate.
estimate_cost`` then billed ``input_tokens x input_rate + cache_read x
cache_rate`` — but because ``input_tokens`` already *includes* the cached
tokens, the cached portion was billed **twice**: once at the full input rate
($1.40/M) and again at the cache-read rate ($0.26/M).

The **rate is correct**: $1.40/M input, $4.40/M output, $0.26/M cached matches
z.ai's published GLM-5.2 pricing. The over-report is entirely the token
double-count, not the rate. (GLM-4.6 is the cheaper $0.60/$2.20 model; GLM-5.2
is a distinct, pricier flagship.)

Contract pinned here:

1. z.ai's OpenAI-shaped usage (prompt_tokens incl cache + nested cached_tokens)
   maps to canonical ``input_tokens`` (incl cache) / ``cache_read_input_tokens``
   — the exact shape that used to double-bill.
2. The corrected cost matches z.ai's own documented example: 100K input / 80%
   cached / 10K output = **$0.0928** (cached tokens billed ONCE, at the cache
   rate).
3. Cache-heavy agentic runs (95% hit) no longer over-report >3x.
4. Anthropic/Claude accounting is UNCHANGED — Claude's ``input_tokens`` already
   excludes cache, so it must NOT be subtracted (that would under-count).
"""

from __future__ import annotations

import json

from model_pricing import ModelRate, load_pricing
from stream_parser import StreamParser

# z.ai / GLM-5.2 published rates (verified 2026-07 against z.ai pricing pages and
# multiple aggregators): input $1.40/M, output $4.40/M, cached input $0.26/M.
_ZAI_INPUT_RATE = 1.40
_ZAI_OUTPUT_RATE = 4.40
_ZAI_CACHE_RATE = 0.26


def _zai_usage_snapshot(
    *, prompt_tokens: int, cached_tokens: int, completion_tokens: int
) -> dict[str, object]:
    """Drive a realistic z.ai OpenAI-shaped usage payload through the real
    StreamParser and return its canonical usage snapshot.

    z.ai's ``/api/anthropic`` stream is Claude-format events; the ``usage``
    object follows z.ai's documented OpenAI shape where ``prompt_tokens``
    INCLUDES ``prompt_tokens_details.cached_tokens``.
    """
    parser = StreamParser()
    result_event = {
        "type": "result",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        },
    }
    parser.parse(json.dumps(result_event))
    return parser.usage_snapshot


def test_zai_openai_usage_maps_to_canonical_input_and_cache_fields() -> None:
    snap = _zai_usage_snapshot(
        prompt_tokens=100_000, cached_tokens=80_000, completion_tokens=10_000
    )
    # prompt_tokens (incl cache) lands in input_tokens — the double-bill shape.
    assert snap["input_tokens"] == 100_000
    assert snap["cache_read_input_tokens"] == 80_000
    assert snap["output_tokens"] == 10_000
    assert snap["cache_creation_input_tokens"] == 0


def test_zai_cached_tokens_billed_once_matches_published_example() -> None:
    """z.ai's caching guide bills 100K input / 80% hit / 10K output at $0.0928.
    HydraFlow must match — cached tokens billed once, at the cache rate."""
    pricing = load_pricing()
    snap = _zai_usage_snapshot(
        prompt_tokens=100_000, cached_tokens=80_000, completion_tokens=10_000
    )

    cost = pricing.estimate_cost(
        "glm-5.2",
        input_tokens=int(snap["input_tokens"]),  # type: ignore[call-overload]
        output_tokens=int(snap["output_tokens"]),  # type: ignore[call-overload]
        cache_write_tokens=int(snap["cache_creation_input_tokens"]),  # type: ignore[call-overload]
        cache_read_tokens=int(snap["cache_read_input_tokens"]),  # type: ignore[call-overload]
    )
    assert cost is not None

    fresh = 100_000 - 80_000
    expected = (
        fresh * _ZAI_INPUT_RATE
        + 10_000 * _ZAI_OUTPUT_RATE
        + 80_000 * _ZAI_CACHE_RATE
    ) / 1_000_000
    assert abs(cost - 0.0928) < 1e-9
    assert abs(cost - expected) < 1e-9

    # Pin the over-count the fix removes: the naive double-count billed the full
    # 100K input at $1.40 AND the 80K cached again at $0.26 == $0.2048.
    double_counted = (
        100_000 * _ZAI_INPUT_RATE
        + 10_000 * _ZAI_OUTPUT_RATE
        + 80_000 * _ZAI_CACHE_RATE
    ) / 1_000_000
    assert abs(double_counted - 0.2048) < 1e-9
    assert cost < double_counted


def test_zai_cache_heavy_run_no_longer_over_reports() -> None:
    """At 95% cache-hit (typical of cache-heavy agentic runs) the pre-fix
    double-count inflated cost >3x. Pin the corrected fresh+cache figure."""
    pricing = load_pricing()
    snap = _zai_usage_snapshot(
        prompt_tokens=1_000_000, cached_tokens=950_000, completion_tokens=20_000
    )
    cost = pricing.estimate_cost(
        "glm-5.2",
        input_tokens=int(snap["input_tokens"]),  # type: ignore[call-overload]
        output_tokens=int(snap["output_tokens"]),  # type: ignore[call-overload]
        cache_write_tokens=int(snap["cache_creation_input_tokens"]),  # type: ignore[call-overload]
        cache_read_tokens=int(snap["cache_read_input_tokens"]),  # type: ignore[call-overload]
    )
    assert cost is not None

    fresh = 1_000_000 - 950_000
    expected = (
        fresh * _ZAI_INPUT_RATE
        + 20_000 * _ZAI_OUTPUT_RATE
        + 950_000 * _ZAI_CACHE_RATE
    ) / 1_000_000
    assert abs(cost - expected) < 1e-9

    double_counted = (
        1_000_000 * _ZAI_INPUT_RATE
        + 20_000 * _ZAI_OUTPUT_RATE
        + 950_000 * _ZAI_CACHE_RATE
    ) / 1_000_000
    assert double_counted / cost > 3.0


def test_claude_anthropic_accounting_unchanged() -> None:
    """Anthropic's ``input_tokens`` EXCLUDES cache; Claude models must NOT
    subtract cache (that would under-count). Cost is unchanged by the fix."""
    pricing = load_pricing()
    cost = pricing.estimate_cost(
        "claude-opus-4-8",
        input_tokens=20_000,  # excludes the 80K cache_read (Anthropic semantics)
        output_tokens=10_000,
        cache_write_tokens=0,
        cache_read_tokens=80_000,
    )
    assert cost is not None
    # opus-4-8: input 5.0, output 25.0, cache_write 6.25, cache_read 0.5.
    expected = (20_000 * 5.0 + 10_000 * 25.0 + 80_000 * 0.5) / 1_000_000
    assert abs(cost - expected) < 1e-9


def test_modelrate_flag_toggles_cache_subtraction() -> None:
    """Unit-level: the ``input_includes_cache`` flag toggles the subtraction;
    the Anthropic default leaves input untouched."""
    common = {
        "input_cost_per_million": 1.40,
        "output_cost_per_million": 4.40,
        "cache_write_cost_per_million": 1.40,
        "cache_read_cost_per_million": 0.26,
    }
    anthropic_rate = ModelRate(**common)
    zai_rate = ModelRate(**common, input_includes_cache=True)

    kwargs = {
        "input_tokens": 100_000,
        "output_tokens": 10_000,
        "cache_read_tokens": 80_000,
    }
    # Anthropic (default) bills the full input; z.ai subtracts the cached tokens.
    assert anthropic_rate.estimate_cost(**kwargs) > zai_rate.estimate_cost(**kwargs)
    assert abs(zai_rate.estimate_cost(**kwargs) - 0.0928) < 1e-9
    # Clamp: cache >= input can't produce a negative billable input.
    assert (
        zai_rate.estimate_cost(
            input_tokens=50_000, output_tokens=0, cache_read_tokens=80_000
        )
        >= 0.0
    )

"""Per-backend cost-accounting conformance pins (issue #10775).

Mined from the z.ai/GLM 6-8x over-report (#10761): ``ModelRate.estimate_cost``
correctness depends on each backend's *usage semantics* — chiefly whether the
reported ``input_tokens`` INCLUDES the cached tokens. The ``zai`` backend
shipped with no per-backend conformance guard, so a per-backend semantics
mismatch double-billed the cached tokens and reached the operator silently.

This module drives a realistic usage payload of EACH distinct backend shape —
Anthropic/Claude, z.ai/GLM, OpenAI/Codex, Gemini, Pi (all through the REAL
:class:`StreamParser`) and Moonshot/Kimi (the one-shot OpenAI-compatible path,
which does not use ``StreamParser``) — through to ``estimate_cost`` and pins the
computed cost against a hand-figure. The point: the next backend addition
cannot silently mis-bill without a red test.

Two usage-semantics families are pinned:

* ``input_includes_cache = False`` (Anthropic/Claude, Pi): ``input_tokens``
  EXCLUDES cache, so cache-read/creation are billed ON TOP — never subtracted.
* ``input_includes_cache = True`` (z.ai/GLM, OpenAI/Codex, Gemini): the
  reported prompt/input count INCLUDES the cached subset, so the cached tokens
  are subtracted from billable input and charged ONCE at the cache rate.

Backends without a pricing-table entry (Codex, Gemini, Pi) are billed against a
*representative* :class:`ModelRate` — their published prices are illustrative;
the conformance property under test is the StreamParser field-mapping + the
cache-once/as-is billing semantics, not the specific dollar rate.
"""

from __future__ import annotations

import json

from cost_plausibility import check_cost_plausibility
from model_pricing import ModelRate, load_pricing
from stream_parser import StreamParser


def _snapshot(*events: dict[str, object]) -> dict[str, object]:
    """Drive raw stream events through the REAL StreamParser, return snapshot."""
    parser = StreamParser()
    for event in events:
        parser.parse(json.dumps(event))
    return parser.usage_snapshot


def _cost(rate: ModelRate, snap: dict[str, object]) -> float:
    """Bill a StreamParser usage snapshot through the real cost path."""
    return rate.estimate_cost(
        input_tokens=int(snap["input_tokens"]),  # type: ignore[call-overload]
        output_tokens=int(snap["output_tokens"]),  # type: ignore[call-overload]
        cache_write_tokens=int(snap["cache_creation_input_tokens"]),  # type: ignore[call-overload]
        cache_read_tokens=int(snap["cache_read_input_tokens"]),  # type: ignore[call-overload]
    )


# --------------------------------------------------------------------------- #
# Anthropic / Claude — input_tokens EXCLUDES cache (billed as-is).
# --------------------------------------------------------------------------- #
def test_anthropic_claude_usage_billed_excluding_cache() -> None:
    """Claude's ``usage.input_tokens`` already excludes cache — cache-read and
    cache-creation are billed ON TOP, never subtracted (the invariant the
    z.ai fix must not disturb)."""
    snap = _snapshot(
        {
            "type": "result",
            "result": "done",
            "usage": {
                "input_tokens": 20_000,  # EXCLUDES the 80K cache_read
                "output_tokens": 10_000,
                "cache_creation_input_tokens": 5_000,
                "cache_read_input_tokens": 80_000,
            },
        }
    )
    assert snap["usage_backend"] == "claude"
    assert snap["input_tokens"] == 20_000
    assert snap["cache_read_input_tokens"] == 80_000
    assert snap["cache_creation_input_tokens"] == 5_000

    rate = load_pricing().get_rate("claude-opus-4-8")
    assert rate is not None
    assert rate.input_includes_cache is False
    # opus-4-8: input 5.0, output 25.0, cache_write 6.25, cache_read 0.5.
    expected = (20_000 * 5.0 + 10_000 * 25.0 + 5_000 * 6.25 + 80_000 * 0.5) / 1_000_000
    assert abs(expected - 0.421250) < 1e-9
    assert abs(_cost(rate, snap) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# z.ai / GLM — OpenAI-shaped usage via the /api/anthropic endpoint.
# prompt_tokens INCLUDES cache; cached billed ONCE (the #10761 fix).
# --------------------------------------------------------------------------- #
def test_zai_glm_openai_usage_bills_cache_once() -> None:
    snap = _snapshot(
        {
            "type": "result",
            "result": "done",
            "usage": {
                "prompt_tokens": 100_000,  # INCLUDES the 80K cached
                "completion_tokens": 10_000,
                "total_tokens": 110_000,
                "prompt_tokens_details": {"cached_tokens": 80_000},
            },
        }
    )
    assert snap["usage_backend"] == "claude"  # z.ai speaks Claude events
    assert snap["input_tokens"] == 100_000  # incl cache — the double-bill shape
    assert snap["cache_read_input_tokens"] == 80_000
    assert snap["cache_creation_input_tokens"] == 0

    rate = load_pricing().get_rate("glm-5.2")
    assert rate is not None
    assert rate.input_includes_cache is True
    # glm-5.2: input 1.40, output 4.40, cache_read 0.26. Cached billed ONCE.
    fresh = 100_000 - 80_000
    expected = (fresh * 1.40 + 10_000 * 4.40 + 80_000 * 0.26) / 1_000_000
    assert abs(expected - 0.092800) < 1e-9  # z.ai's own published example
    assert abs(_cost(rate, snap) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# OpenAI / Codex — item.completed events; input_tokens INCLUDES cached, with
# reasoning tokens carried inside output (never double-billed).
# --------------------------------------------------------------------------- #
# Representative OpenAI rate (illustrative — no pricing-table entry today).
_CODEX_RATE = ModelRate(
    input_cost_per_million=1.25,
    output_cost_per_million=10.0,
    cache_write_cost_per_million=1.25,
    cache_read_cost_per_million=0.125,
    input_includes_cache=True,
)


def test_codex_openai_usage_maps_and_bills_cache_once() -> None:
    snap = _snapshot(
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "usage": {
                    "input_tokens": 50_000,  # INCLUDES the 40K cached
                    "output_tokens": 8_000,  # already includes reasoning
                    "total_tokens": 58_000,
                    "input_tokens_details": {"cached_tokens": 40_000},
                    "output_tokens_details": {"reasoning_tokens": 3_000},
                },
            },
        },
        {"type": "turn.completed"},
    )
    assert snap["usage_backend"] == "codex"
    assert snap["input_tokens"] == 50_000
    assert snap["cache_read_input_tokens"] == 40_000  # nested cached_tokens
    assert snap["output_tokens"] == 8_000  # reasoning_tokens NOT added on top
    assert snap["cache_creation_input_tokens"] == 0

    fresh = 50_000 - 40_000
    expected = (fresh * 1.25 + 8_000 * 10.0 + 40_000 * 0.125) / 1_000_000
    assert abs(expected - 0.097500) < 1e-9
    assert abs(_cost(_CODEX_RATE, snap) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Gemini — init locks the backend, result carries ``stats``; promptTokenCount
# INCLUDES cachedContentTokenCount, so cached is billed once.
# --------------------------------------------------------------------------- #
_GEMINI_RATE = ModelRate(
    input_cost_per_million=1.25,
    output_cost_per_million=10.0,
    cache_write_cost_per_million=1.25,
    cache_read_cost_per_million=0.31,
    input_includes_cache=True,
)


def test_gemini_stats_usage_maps_and_bills_cache_once() -> None:
    snap = _snapshot(
        {"type": "init", "session_id": "s1", "model": "gemini-3.1-pro-preview"},
        {
            "type": "result",
            "result": "done",
            "stats": {
                "input_tokens": 30_000,  # INCLUDES the 24K cached
                "output_tokens": 5_000,
                "cached": 24_000,
                "total_tokens": 35_000,
            },
        },
    )
    assert snap["usage_backend"] == "gemini"
    assert snap["input_tokens"] == 30_000
    assert snap["cache_read_input_tokens"] == 24_000  # "cached" -> cache_read
    assert snap["output_tokens"] == 5_000

    fresh = 30_000 - 24_000
    expected = (fresh * 1.25 + 5_000 * 10.0 + 24_000 * 0.31) / 1_000_000
    assert abs(expected - 0.064940) < 1e-9
    assert abs(_cost(_GEMINI_RATE, snap) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Pi — message_end usage with SEPARATE cacheRead/cacheWrite; input EXCLUDES
# cache (Anthropic-style), so cache is billed on top, never subtracted.
# --------------------------------------------------------------------------- #
_PI_RATE = ModelRate(
    input_cost_per_million=3.0,
    output_cost_per_million=15.0,
    cache_write_cost_per_million=3.75,
    cache_read_cost_per_million=0.3,
    input_includes_cache=False,
)


def test_pi_usage_maps_and_bills_excluding_cache() -> None:
    snap = _snapshot(
        {
            "type": "message_end",
            "usage": {
                "input_tokens": 40_000,  # EXCLUDES cache (separate fields)
                "output_tokens": 6_000,
                "cacheRead": 20_000,
                "cacheWrite": 2_000,
            },
        }
    )
    assert snap["usage_backend"] == "pi"
    assert snap["input_tokens"] == 40_000
    assert snap["cache_read_input_tokens"] == 20_000
    assert snap["cache_creation_input_tokens"] == 2_000
    assert snap["output_tokens"] == 6_000

    expected = (40_000 * 3.0 + 6_000 * 15.0 + 2_000 * 3.75 + 20_000 * 0.3) / 1_000_000
    assert abs(expected - 0.223500) < 1e-9
    assert abs(_cost(_PI_RATE, snap) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Moonshot / Kimi — one-shot OpenAI-compatible path (runner_utils.py, NOT
# StreamParser). That path reads ONLY prompt_tokens/completion_tokens and
# captures NO cache (see run_utils usage_out mapping), so kimi-k3's default
# ``input_includes_cache = False`` is correct: no cache to double-count.
# --------------------------------------------------------------------------- #
def test_moonshot_kimi_oneshot_usage_bills_without_cache_double_count() -> None:
    # The one-shot backend surfaces the OpenAI response usage as input/output
    # only; cache tokens are not observed on this path.
    oneshot_usage = {
        "input_tokens": 50_000,  # from prompt_tokens
        "output_tokens": 8_000,  # from completion_tokens
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
    }
    rate = load_pricing().get_rate("kimi-k3")
    assert rate is not None
    assert rate.input_includes_cache is False

    cost = rate.estimate_cost(**oneshot_usage)
    # kimi-k3: input 2.0, output 5.0. No cache observed -> billed straight.
    expected = (50_000 * 2.0 + 8_000 * 5.0) / 1_000_000
    assert abs(expected - 0.140000) < 1e-9
    assert abs(cost - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Every pinned backend shape is cost-plausible against its own peak table rate
# (the guard must not false-positive on any correct billing).
# --------------------------------------------------------------------------- #
def test_all_backend_shapes_are_cost_plausible() -> None:
    pricing = load_pricing()
    cases = [
        ("claude-opus-4-8", pricing.get_rate("claude-opus-4-8"), 0.421250, 115_000),
        ("glm-5.2", pricing.get_rate("glm-5.2"), 0.092800, 190_000),
        ("codex-representative", _CODEX_RATE, 0.097500, 98_000),
        ("gemini-representative", _GEMINI_RATE, 0.064940, 59_000),
        ("pi-representative", _PI_RATE, 0.223500, 68_000),
        ("kimi-k3", pricing.get_rate("kimi-k3"), 0.140000, 58_000),
    ]
    for model, rate, cost, total_tokens in cases:
        assert rate is not None
        # Correct billing's effective rate can never exceed peak -> no anomaly,
        # even at the tight K=1.0 ceiling.
        anomaly = check_cost_plausibility(
            model=model,
            cost_usd=cost,
            total_tokens=total_tokens,
            rate=rate,
            threshold=1.0,
        )
        assert anomaly is None, f"{model} falsely flagged: {anomaly}"


# --------------------------------------------------------------------------- #
# The plausibility guard WOULD flag a per-backend mis-bill: a model billing
# tokens absent from the token totals pushes effective past its peak rate.
# --------------------------------------------------------------------------- #
def test_plausibility_guard_flags_double_counted_mis_bill() -> None:
    # glm-5.2 peak rate is $4.40/M. Simulate an aggregate row whose recorded
    # cost is far larger than any 1,000-token mix could legitimately cost
    # (e.g. cost attributed against tokens that were never counted).
    rate = load_pricing().get_rate("glm-5.2")
    assert rate is not None
    anomaly = check_cost_plausibility(
        model="glm-5.2",
        cost_usd=0.10,  # $100/M effective over 1,000 tokens
        total_tokens=1_000,
        rate=rate,
        threshold=3.0,
    )
    assert anomaly is not None
    assert anomaly.peak_rate_per_million == 4.40
    assert anomaly.ratio > 3.0
    d = anomaly.as_dict()
    assert d["model"] == "glm-5.2"
    assert d["effective_rate_per_million"] == 100.0

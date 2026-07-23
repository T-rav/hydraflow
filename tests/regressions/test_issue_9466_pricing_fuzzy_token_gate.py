"""Regression #9466: get_rate fuzzy fallback must not silently mis-rate
unknown model ids.

``ModelPricingTable.get_rate()`` used to fall back to a bare substring scan:
any model string containing an alias resolved to that alias's entry. Because
the tier aliases ``opus``/``sonnet``/``haiku`` are substrings of essentially
every Claude id, an unknown-but-plausible future id (e.g. a ``claude-opus-4-9``
before its entry lands) silently inherited whatever entry currently owned
``opus`` — a wrong-but-nonzero rate instead of ``None``.

Tightened contract (design choice: return ``None`` + one-time warning, never a
guessed stale price — this feeds the #9821 cost-unknown surfaces, which must
show 'unknown', never $0):

* fuzzy candidates are canonical ids and multi-token aliases only; bare tier
  aliases never fuzzy-match;
* candidates must align on token boundaries, and a numeric token immediately
  after the match (a version bump) rejects it;
* every fuzzy hit and every unknown model emits a one-time log signal.

These pins run against the REAL shipped pricing table. The sentinel id embeds
``opus`` (so the old substring scan would have mis-rated it) plus a marker
suffix that must never become a real model id.
"""

from __future__ import annotations

import logging

from model_pricing import load_pricing

# Old code: "opus" (alias of claude-opus-4-7) is a substring -> mis-rated at
# the opus tier price. Also "claude-opus-4" (alias of claude-opus-4-20250514)
# is a token-boundary prefix, but the numeric residual "9" marks a newer
# version, so the gated fallback must reject it too.
_UNKNOWN_OPUS_SENTINEL = "claude-opus-4-9-issue-9466-sentinel"


def test_unknown_opus_family_id_returns_none_not_stale_tier_price() -> None:
    assert load_pricing().get_rate(_UNKNOWN_OPUS_SENTINEL) is None


def test_unknown_opus_family_id_cost_is_unknown_not_zero() -> None:
    # Feeds the #9821 contract: estimate_cost None => cost_unknown surfaces,
    # never $0.
    cost = load_pricing().estimate_cost(
        _UNKNOWN_OPUS_SENTINEL, input_tokens=1000, output_tokens=1000
    )
    assert cost is None


def test_unknown_model_emits_one_time_warning() -> None:
    pricing = load_pricing()
    logger = logging.getLogger("hydraflow.model_pricing")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        assert pricing.get_rate(_UNKNOWN_OPUS_SENTINEL) is None
        assert pricing.get_rate(_UNKNOWN_OPUS_SENTINEL) is None
    finally:
        logger.removeHandler(handler)
    warnings = [
        r
        for r in records
        if r.levelno == logging.WARNING and _UNKNOWN_OPUS_SENTINEL in r.getMessage()
    ]
    assert len(warnings) == 1


def test_bare_tier_aliases_still_resolve_exactly() -> None:
    # The exact-alias path is untouched by the fuzzy gate.
    pricing = load_pricing()
    for alias in ("opus", "sonnet", "haiku"):
        assert pricing.get_rate(alias) is not None, alias


def test_token_boundary_variant_suffix_still_resolves() -> None:
    # The legitimate fuzzy case survives the gate: a full known id followed by
    # a non-numeric variant token.
    rate = load_pricing().get_rate("claude-sonnet-4-6-preview")
    assert rate is not None
    assert rate.input_cost_per_million == 3.0

"""Regression: CLI-harness inference rows must bill Anthropic-shaped input in full.

Follow-up to the gateway fix (#11528). The Claude CLI under credit failover
(ADR-0119) or ``repo_provider=zai`` talks to z.ai's Anthropic-compatible
endpoint: its stream-json usage is Anthropic-shaped (``input_tokens`` EXCLUDES
cache). ``telemetry_tool_for_transport`` marks those rows ``tool="zai"`` — the
same marker the one-shot OpenAI-compat client uses, whose ``prompt_tokens``
INCLUDES cache. Every inference-side pricing site priced by the model id alone,
so the table's ``input_includes_cache: true`` for ``glm-5.2`` subtracted the
cache from CLI-harness rows. Live proof from the audit: a glm-5.2 CLI row with
``input=106647 / output=47751 / cache_read=4889664`` billed
``max(0, 106647 - 4889664) = 0`` input tokens — ``$0.149`` dropped.

Cache-inclusiveness is keyed on TRANSPORT, not model id:

* writers stamp ``usage_shape`` ("anthropic" | "openai_compat") from the CLI /
  client that PRODUCED the counts, never from the transport-rewritten tool marker;
* every reader derives the override through ONE helper
  (``model_pricing.input_includes_cache_for``); legacy rows without the stamp
  default by tool (Claude CLI / gateway → exclusive; anything else → table
  default) with the #11528 impossible-counts guard as the last line of defense.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dashboard_routes._cost_rollups import iter_priced_inferences
from dashboard_routes._waterfall_builder import _action_llm
from model_pricing import USAGE_SHAPE_ANTHROPIC, load_pricing
from prompt_telemetry import PromptTelemetry
from tests.helpers import ConfigFactory

# Exact live glm-5.2 CLI-harness row from the audit.
_LIVE_INPUT = 106_647
_LIVE_OUTPUT = 47_751
_LIVE_CACHE_READ = 4_889_664
# GLM-5.2 published rate: $1.40/M input, $4.40/M output, $0.26/M cached input.
_IN, _OUT, _CACHE = 1.4, 4.4, 0.26


def _exclusive(input_tokens: int, output_tokens: int, cache_read: int) -> float:
    return (_IN * input_tokens + _OUT * output_tokens + _CACHE * cache_read) / 1e6


def _inclusive(input_tokens: int, output_tokens: int, cache_read: int) -> float:
    return (
        _IN * (input_tokens - cache_read) + _OUT * output_tokens + _CACHE * cache_read
    ) / 1e6


def test_live_cli_harness_row_bills_full_input_when_stamped_anthropic(tmp_path):
    config = ConfigFactory.create(repo_root=tmp_path)
    PromptTelemetry(config).record(
        source="implementer",
        tool="zai",  # transport marker the Claude CLI wears under credit failover
        model="glm-5.2",
        issue_number=1,
        pr_number=None,
        session_id="s",
        prompt_chars=10,
        transcript_chars=10,
        duration_seconds=1.0,
        success=True,
        stats={
            "input_tokens": _LIVE_INPUT,
            "output_tokens": _LIVE_OUTPUT,
            "cache_read_input_tokens": _LIVE_CACHE_READ,
        },
        usage_shape=USAGE_SHAPE_ANTHROPIC,
    )

    row = json.loads(config.cost_inferences_path.read_text().strip())

    assert row["usage_shape"] == "anthropic"
    assert row["estimated_cost_usd"] == pytest.approx(
        round(_exclusive(_LIVE_INPUT, _LIVE_OUTPUT, _LIVE_CACHE_READ), 6), abs=1e-6
    )
    # The dropped amount: the whole input component, ~$0.149.
    assert pytest.approx(0.149, abs=0.001) == _IN * _LIVE_INPUT / 1e6


def test_live_row_is_rescued_by_the_guard_even_without_a_stamp(tmp_path):
    """input < cache_read is impossible under inclusive semantics, so the
    #11528 guard bills the legacy (unstamped, ambiguous ``zai``) row exclusive."""
    config = ConfigFactory.create(repo_root=tmp_path)
    PromptTelemetry(config).record(
        source="implementer",
        tool="zai",
        model="glm-5.2",
        issue_number=1,
        pr_number=None,
        session_id="s",
        prompt_chars=10,
        transcript_chars=10,
        duration_seconds=1.0,
        success=True,
        stats={
            "input_tokens": _LIVE_INPUT,
            "output_tokens": _LIVE_OUTPUT,
            "cache_read_input_tokens": _LIVE_CACHE_READ,
        },
    )

    row = json.loads(config.cost_inferences_path.read_text().strip())

    assert row["usage_shape"] is None
    assert row["estimated_cost_usd"] == pytest.approx(
        round(_exclusive(_LIVE_INPUT, _LIVE_OUTPUT, _LIVE_CACHE_READ), 6), abs=1e-6
    )


# Guard-blind counts: input >= cache_read, so only the transport rule decides.
_BIG_INPUT, _BIG_OUTPUT, _BIG_CACHE = 5_000_000, 100_000, 4_000_000


def _write_row(config, **fields) -> None:
    base = {
        "timestamp": (datetime(2026, 8, 21, 12, tzinfo=UTC)).isoformat(),
        "source": "implementer",
        "model": "glm-5.2",
        "issue_number": 7,
        "input_tokens": _BIG_INPUT,
        "output_tokens": _BIG_OUTPUT,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": _BIG_CACHE,
        "duration_seconds": 1.0,
        "status": "success",
    }
    base.update(fields)
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(base) + "\n")


def test_readers_price_stamped_and_legacy_rows_by_transport_rule(tmp_path):
    config = ConfigFactory.create(repo_root=tmp_path)
    _write_row(config, source="stamped-zai", tool="zai", usage_shape="anthropic")
    _write_row(config, source="legacy-claude", tool="claude")
    _write_row(config, source="legacy-gateway", tool="gateway")
    _write_row(config, source="legacy-zai", tool="zai")
    _write_row(config, source="one-shot-zai", tool="zai", usage_shape="openai_compat")

    since = datetime(2026, 8, 21, tzinfo=UTC)
    priced = {
        rec["source"]: rec["cost_usd"]
        for rec in iter_priced_inferences(
            config, since=since, until=since + timedelta(days=1), pricing=load_pricing()
        )
    }

    exclusive = round(_exclusive(_BIG_INPUT, _BIG_OUTPUT, _BIG_CACHE), 6)
    inclusive = round(_inclusive(_BIG_INPUT, _BIG_OUTPUT, _BIG_CACHE), 6)
    assert exclusive != inclusive
    # Stamped Anthropic-shaped rows and legacy Claude-CLI/gateway rows: exclusive.
    assert priced["stamped-zai"] == pytest.approx(exclusive, abs=1e-6)
    assert priced["legacy-claude"] == pytest.approx(exclusive, abs=1e-6)
    assert priced["legacy-gateway"] == pytest.approx(exclusive, abs=1e-6)
    # One-shot and ambiguous legacy ``zai`` rows: the table default (inclusive
    # for GLM) — the documented limit of what a legacy row can tell us.
    assert priced["one-shot-zai"] == pytest.approx(inclusive, abs=1e-6)
    assert priced["legacy-zai"] == pytest.approx(inclusive, abs=1e-6)


def test_waterfall_action_prices_stamped_row_exclusive():
    rec = {
        "model": "glm-5.2",
        "tool": "zai",
        "usage_shape": "anthropic",
        "input_tokens": _BIG_INPUT,
        "output_tokens": _BIG_OUTPUT,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": _BIG_CACHE,
        "timestamp": "2026-08-21T12:00:00+00:00",
        "duration_seconds": 1.0,
    }

    action = _action_llm(rec, load_pricing())

    assert action["cost_unknown"] is False
    assert action["cost_usd"] == pytest.approx(
        round(_exclusive(_BIG_INPUT, _BIG_OUTPUT, _BIG_CACHE), 6), abs=1e-6
    )

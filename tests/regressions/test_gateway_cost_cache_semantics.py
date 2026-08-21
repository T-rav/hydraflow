"""Regression: gateway cost must bill Anthropic-shaped input in full (cache excluded).

The LLM gateway proxies Anthropic-shaped streams (``message_start`` /
``message_delta`` usage) for EVERY upstream, z.ai's GLM harness included. The
pricing table marks ``glm-5.2`` ``input_includes_cache: true`` because the
OpenAI-compatible one-shot face reports ``prompt_tokens`` INCLUDING cached
tokens (#10761). The gateway reused that model-keyed flag on a stream whose
``input_tokens`` already EXCLUDES cache, so a live row with
``input_tokens=1244`` and ``cache_read_input_tokens=46784`` billed
``max(0, 1244 - 46784) = 0`` input tokens. 276 of 310 live ledger rows had
``input_tokens < cache_read_input_tokens``; all 310 were ``cost_unknown``
because ``glm-5.3`` (the model z.ai actually served) had no pricing entry.

Cache-inclusiveness is a property of the usage SHAPE, not the model id:

* callers can override the table default per call — the gateway passes
  ``input_includes_cache=False``; the one-shot path keeps the table's True;
* the rate never subtracts when ``input_tokens`` is smaller than the cached
  counts (impossible under inclusive semantics) and bills exclusive instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding, RepoClass
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from model_pricing import ModelRate, load_pricing

# Exact shape of one live ``zai-harness`` ledger row (2026-08-20).
_LIVE_INPUT = 1244
_LIVE_CACHE_READ = 46784
_LIVE_OUTPUT = 532
# GLM-5.2 / GLM-5.3 published rate: $1.40/M input, $4.40/M output, $0.26/M cached
# (https://docs.z.ai/guides/overview/pricing).
_GLM_INPUT_RATE = 1.4
_GLM_OUTPUT_RATE = 4.4
_GLM_CACHE_READ_RATE = 0.26


def _exclusive_cost(input_tokens: int, output_tokens: int, cache_read: int) -> float:
    return (
        _GLM_INPUT_RATE * input_tokens
        + _GLM_OUTPUT_RATE * output_tokens
        + _GLM_CACHE_READ_RATE * cache_read
    ) / 1_000_000


def _zai_sse(input_tokens: int) -> bytes:
    """z.ai's Anthropic-compatible stream: empty ``message_start`` usage, all
    counts in the final ``message_delta``."""
    return (
        b'event: message_start\ndata: {"type":"message_start","message":'
        b'{"id":"msg-zai","model":"glm-5.3","usage":{}}}\n\n'
        b'event: message_delta\ndata: {"type":"message_delta","delta":'
        b'{"stop_reason":"end_turn"},"usage":{"input_tokens":'
        + str(input_tokens).encode()
        + b',"output_tokens":'
        + str(_LIVE_OUTPUT).encode()
        + b',"cache_read_input_tokens":'
        + str(_LIVE_CACHE_READ).encode()
        + b',"cache_creation_input_tokens":0}}\n\n'
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )


def _glm_rate() -> ModelRate:
    rate = load_pricing().get_rate("glm-5.2")
    assert rate is not None
    assert rate.input_includes_cache is True, "one-shot GLM face is inclusive"
    return rate


class TestRateCacheSemantics:
    def test_live_shape_with_explicit_exclusive_override_bills_full_input(
        self,
    ) -> None:
        cost = _glm_rate().estimate_cost(
            _LIVE_INPUT,
            _LIVE_OUTPUT,
            cache_read_tokens=_LIVE_CACHE_READ,
            input_includes_cache=False,
        )

        assert cost == pytest.approx(
            _exclusive_cost(_LIVE_INPUT, _LIVE_OUTPUT, _LIVE_CACHE_READ)
        )

    def test_impossible_inclusive_counts_fall_back_to_exclusive_billing(
        self,
    ) -> None:
        # Table default (inclusive) but input < cache_read: never subtract.
        cost = _glm_rate().estimate_cost(
            _LIVE_INPUT, _LIVE_OUTPUT, cache_read_tokens=_LIVE_CACHE_READ
        )

        assert cost == pytest.approx(
            _exclusive_cost(_LIVE_INPUT, _LIVE_OUTPUT, _LIVE_CACHE_READ)
        )

    def test_one_shot_inclusive_default_still_subtracts_plausible_cache(
        self,
    ) -> None:
        # Pins the OpenAI-compat one-shot path: prompt_tokens (50000) includes
        # the cached 46784, so only 3216 bill at the input rate.
        cost = _glm_rate().estimate_cost(50_000, 0, cache_read_tokens=_LIVE_CACHE_READ)

        assert cost == pytest.approx(
            (
                _GLM_INPUT_RATE * (50_000 - _LIVE_CACHE_READ)
                + _GLM_CACHE_READ_RATE * _LIVE_CACHE_READ
            )
            / 1_000_000
        )


class _ChunkStream(httpx.AsyncByteStream):
    """Lazily streamed upstream body (``content=`` is read eagerly by httpx)."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def _gateway(
    tmp_path: Path, sse: bytes
) -> tuple[httpx.AsyncClient, str, GatewayLedger]:
    settings = GatewaySettings(
        control_token=SecretStr("test-control-token-0123456789abcdef"),
        upstreams={
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://zai.test",
                api_key=SecretStr("real-zai-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            ),
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ZAI_HARNESS,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    ledger = GatewayLedger(settings.ledger_path)

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkStream([sse[:40], sse[40:]]),
        )

    app = create_app(
        settings,
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        ledger=ledger,
        body_store=GatewayBodyStore(settings.body_dir),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    )
    return client, minted.token, ledger


@pytest.mark.parametrize(
    "input_tokens",
    [
        pytest.param(_LIVE_INPUT, id="live-shape-input-below-cache"),
        # input >= cache_read: the impossible-counts guard cannot rescue this
        # row — only the gateway's explicit shape override keeps input intact.
        pytest.param(50_000, id="guard-blind-input-above-cache"),
    ],
)
async def test_gateway_ledger_row_prices_zai_stream_as_exclusive(
    tmp_path: Path, input_tokens: int
) -> None:
    client, token, ledger = _gateway(tmp_path, _zai_sse(input_tokens))
    try:
        response = await client.post(
            "/v1/messages",
            headers={"authorization": f"Bearer {token}"},
            json={"model": "glm-5.2", "messages": []},
        )
    finally:
        await client.aclose()

    assert response.status_code == 200
    (row,) = ledger.read_all()
    assert row.model_requested == "glm-5.2"
    assert row.model_served == "glm-5.3"
    assert row.input_tokens == input_tokens
    assert row.cache_read_input_tokens == _LIVE_CACHE_READ
    assert row.usage_complete is True
    assert row.cost_unknown is False
    assert row.cost_usd == pytest.approx(
        _exclusive_cost(input_tokens, _LIVE_OUTPUT, _LIVE_CACHE_READ)
    )

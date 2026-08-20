from __future__ import annotations

import json

import httpx
import pytest
import scripts.gateway_probe as probe_module
from scripts.gateway_probe import run_probe


class _AsyncBytes(httpx.AsyncByteStream):
    def __init__(self, value: bytes) -> None:
        self._value = value

    async def __aiter__(self):
        yield self._value


def _sse(*payloads: dict) -> bytes:
    return b"".join(
        b"event: message\n" + b"data: " + json.dumps(payload).encode() + b"\n\n"
        for payload in payloads
    )


def test_probe_owned_client_ignores_ambient_proxy_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(probe_module.httpx, "AsyncClient", factory)

    assert probe_module._new_probe_client() is sentinel
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_probe_completes_two_turn_tool_session_without_exposing_tokens() -> None:
    requests: list[httpx.Request] = []
    first = _sse(
        {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "id": "toolu_probe",
                "name": "gateway_probe_echo",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"value":'},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '"tap-ok"}'},
        },
        {"type": "message_stop"},
    )
    second = _sse(
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "probe-complete"},
        },
        {"type": "message_stop"},
    )
    turns = iter((first, second))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/control/v1/keys":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-probe",
                    "token": "virtual-secret",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"key_id": "key-probe", "revoked": True})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(next(turns)),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence = await run_probe(
            gateway_base_url="http://gateway",
            control_token="control-secret",
            model="claude-test",
            client=client,
        )

    assert evidence.tool_use_observed is True
    assert evidence.completion_observed is True
    assert evidence.first_turn.byte_count == len(first)
    assert evidence.second_turn.byte_count == len(second)
    serialized = json.dumps(evidence, default=lambda value: value.__dict__)
    assert "virtual-secret" not in serialized
    assert "control-secret" not in serialized
    assert len(requests) == 4
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/control/v1/keys/key-probe"


@pytest.mark.asyncio
async def test_probe_fails_closed_when_key_mint_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "no"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="key mint failed with HTTP 401"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="wrong",
                model="claude-test",
                client=client,
            )


@pytest.mark.asyncio
async def test_probe_revokes_key_when_agentic_turn_fails() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/control/v1/keys":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-failed-probe",
                    "token": "virtual-secret",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(
                200, json={"key_id": "key-failed-probe", "revoked": True}
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(_sse({"type": "message_stop"})),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="did not observe the forced tool use"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="claude-test",
                client=client,
            )

    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/control/v1/keys/key-failed-probe"


@pytest.mark.asyncio
async def test_probe_fails_when_key_revocation_is_not_acknowledged() -> None:
    first = _sse(
        {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "id": "toolu_probe",
                "name": "gateway_probe_echo",
                "input": {"value": "tap-ok"},
            },
        },
        {"type": "message_stop"},
    )
    second = _sse({"type": "message_stop"})
    turns = iter((first, second))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/control/v1/keys":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-probe",
                    "token": "virtual-secret",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(503)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(next(turns)),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="key revocation failed with HTTP 503"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="claude-test",
                client=client,
            )

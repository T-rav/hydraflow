"""Transparent proxy tests across auth, bytes, headers, errors, and ledgering."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Message, Receive, Scope

from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import (
    GatewayBodyCapture,
    GatewayBodyStore,
    GatewayLedger,
)
from hydraflow_gateway.models import (
    GatewayIdentity,
    MintKeyRequest,
    Principal,
    ProviderBinding,
    RepoClass,
    RouteBinding,
    legacy_account_id,
)
from hydraflow_gateway.proxy import (
    GatewayProxy,
    build_upstream_url,
    sanitized_request_path,
)
from hydraflow_gateway.routing_accounts import load_account_pool
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from model_pricing import load_pricing

_SSE_BYTES = (
    b'event: message_start\r\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":11,'
    b'"cache_creation_input_tokens":3,"cache_read_input_tokens":4}}}\r\n\r\n'
    b'event: content_block_start\ndata: {"type":"content_block_start",'
    b'"index":0,"content_block":{"type":"tool_use","id":"tool-1",'
    b'"name":"Read","input":{}}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","usage":'
    b'{"output_tokens":17}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"

# z.ai's Anthropic-compatible stream: ``message_start`` carries ``usage: {}``
# and every count arrives only in the final ``message_delta``. The served
# model (glm-5.3) differs from the requested one (glm-5.2), as observed live.
_ZAI_SSE_BYTES = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"id":"msg-zai","model":"glm-5.3","usage":{}}}\n\n'
    b'event: content_block_delta\ndata: {"type":"content_block_delta",'
    b'"index":0,"delta":{"type":"text_delta","text":"ok"}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","delta":'
    b'{"stop_reason":"end_turn"},"usage":{"input_tokens":1244,'
    b'"output_tokens":532,"cache_read_input_tokens":46784,'
    b'"cache_creation_input_tokens":0}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)
# GLM-5.3 published rate ($1.40/M in, $4.40/M out, $0.26/M cached) applied to
# the Anthropic-shaped counts above: input is billed in FULL, cache excluded.
_ZAI_EXPECTED_COST = (1.4 * 1244 + 4.4 * 532 + 0.26 * 46784) / 1_000_000


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _BlockingStream(httpx.AsyncByteStream):
    """Yield one chunk, then block until closed — a stream the client abandons."""

    def __init__(self, first_chunk: bytes) -> None:
        self._first_chunk = first_chunk
        self._released = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._first_chunk
        await self._released.wait()

    async def aclose(self) -> None:
        self.closed = True
        self._released.set()


def _mint_request(
    *,
    provider: ProviderBinding = ProviderBinding.ANTHROPIC,
    capture_bodies: bool = True,
    repo_class: RepoClass = RepoClass.HYDRAFLOW,
    issue_number: int | None = None,
    pr_number: int | None = None,
) -> MintKeyRequest:
    return MintKeyRequest(
        principal_kind="spawn",
        principal_id="implementer",
        spawn_id="spawn-1",
        session_id="session-1",
        issue_number=issue_number,
        pr_number=pr_number,
        repo_slug="acme/hydraflow",
        repo_class=repo_class,
        provider_binding=provider,
        capture_bodies=capture_bodies,
        ttl_seconds=300,
    )


def _settings(
    tmp_path: Path, *, max_request_bytes: int = 33_554_432
) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test/prefix",
                api_key=SecretStr("real-anthropic-key"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            ),
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://zai.test",
                api_key=SecretStr("real-zai-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            ),
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
        max_request_bytes=max_request_bytes,
    )


def _gateway_client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    provider: ProviderBinding = ProviderBinding.ANTHROPIC,
    capture_bodies: bool = True,
    repo_class: RepoClass = RepoClass.HYDRAFLOW,
    max_request_bytes: int = 33_554_432,
    issue_number: int | None = None,
    pr_number: int | None = None,
) -> tuple[httpx.AsyncClient, str, GatewayLedger]:
    settings = _settings(tmp_path, max_request_bytes=max_request_bytes)
    store = VirtualKeyStore(
        max_ttl_seconds=600,
        id_factory=lambda: "key-1",
        secret_factory=lambda: "virtual-secret",
        body_capture_repo_slugs=frozenset({"acme/hydraflow"}),
    )
    minted = store.mint(
        _mint_request(
            provider=provider,
            capture_bodies=capture_bodies,
            repo_class=repo_class,
            issue_number=issue_number,
            pr_number=pr_number,
        )
    )
    ledger = GatewayLedger(settings.ledger_path)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(
        settings,
        key_store=store,
        client=upstream_client,
        ledger=ledger,
        body_store=GatewayBodyStore(settings.body_dir),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    )
    return client, minted.token, ledger


def _direct_gateway_proxy(
    tmp_path: Path,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> tuple[GatewayProxy, GatewayIdentity, GatewayLedger, httpx.AsyncClient]:
    settings = _settings(tmp_path)
    store = VirtualKeyStore(
        max_ttl_seconds=600,
        id_factory=lambda: "key-1",
        secret_factory=lambda: "virtual-secret",
        body_capture_repo_slugs=frozenset({"acme/hydraflow"}),
    )
    minted = store.mint(_mint_request())
    identity = store.resolve(minted.token)
    ledger = GatewayLedger(settings.ledger_path)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=ledger,
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        request_id_factory=lambda: "request-1",
    )
    return proxy, identity, ledger, upstream_client


def _streaming_request(receive: Receive) -> Request:
    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/messages",
            "raw_path": b"/v1/messages",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "server": ("gateway.test", 80),
            "client": ("127.0.0.1", 12345),
        },
    )
    return Request(scope, receive)


class TestGatewayProxy:
    async def test_forwards_raw_sse_and_records_usage_without_mutation(
        self, tmp_path: Path
    ) -> None:
        observed: dict[str, Any] = {}
        stream = _ChunkStream([_SSE_BYTES[:31], _SSE_BYTES[31:177], _SSE_BYTES[177:]])

        async def upstream(request: httpx.Request) -> httpx.Response:
            observed["method"] = request.method
            observed["url"] = str(request.url)
            observed["headers"] = request.headers.raw
            observed["body"] = await request.aread()
            return httpx.Response(
                200,
                headers=[
                    ("content-type", "text/event-stream"),
                    ("content-encoding", "identity"),
                    ("set-cookie", "one=1"),
                    ("set-cookie", "two=2"),
                    ("connection", "x-upstream-hop"),
                    ("x-upstream-hop", "remove-me"),
                    ("x-api-key", "must-not-return"),
                    ("authorization", "Bearer must-not-return"),
                ],
                stream=stream,
            )

        client, token, ledger = _gateway_client(tmp_path, upstream)
        request_body = b'{"model":"claude-requested","messages":[]}'
        try:
            response = await client.post(
                "/v1/messages/special%2Fpart?x=1&x=2",
                content=request_body,
                headers=[
                    ("authorization", f"Bearer {token}"),
                    ("content-type", "application/json"),
                    ("anthropic-beta", "oauth-2025-04-20"),
                    ("anthropic-version", "2023-06-01"),
                    ("connection", "x-client-hop"),
                    ("x-client-hop", "remove-me"),
                ],
            )
        finally:
            await client.aclose()

        assert response.status_code == 200
        assert response.content == _SSE_BYTES
        assert response.headers.get_list("set-cookie") == ["one=1", "two=2"]
        assert "x-upstream-hop" not in response.headers
        assert "x-api-key" not in response.headers
        assert "authorization" not in response.headers
        assert response.headers["content-encoding"] == "identity"
        assert observed["method"] == "POST"
        assert observed["url"] == (
            "https://upstream.test/prefix/v1/messages/special%2Fpart?x=1&x=2"
        )
        assert observed["body"] == request_body
        upstream_headers = httpx.Headers(observed["headers"])
        assert upstream_headers["x-api-key"] == "real-anthropic-key"
        assert "authorization" not in upstream_headers
        assert upstream_headers["anthropic-beta"] == "oauth-2025-04-20"
        assert upstream_headers["anthropic-version"] == "2023-06-01"
        assert "x-client-hop" not in upstream_headers
        assert stream.closed is True

        rows = ledger.read_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status_code == 200
        assert row.status == "completed"
        assert row.completed is True
        assert row.client_aborted is False
        assert row.model_requested == "claude-requested"
        assert row.model_served == "claude-sonnet-4-6"
        assert row.input_tokens == 11
        assert row.output_tokens == 17
        assert row.cache_read_input_tokens == 4
        assert row.cache_creation_input_tokens == 3
        assert row.cost_unknown is False
        assert row.cost_usd == 0.00030045
        assert row.usage_complete is True
        assert row.path == "/v1/messages/special/part"
        assert row.timestamp.tzinfo is not None
        assert row.request_id
        assert row.source == "gateway"
        assert row.body_capture_complete is True
        assert (tmp_path / "bodies" / "key-1.request.body").exists() is False
        body_files = sorted((tmp_path / "bodies").glob("*"))
        assert [path.read_bytes() for path in body_files] == [
            request_body,
            _SSE_BYTES,
        ]

    @pytest.mark.parametrize(
        "status_code, body",
        [
            (429, b'{"type":"error","error":{"type":"rate_limit_error"}}'),
            (529, b'{"type":"error","error":{"type":"overloaded_error"}}'),
        ],
    )
    async def test_passes_upstream_errors_verbatim_without_retry(
        self, tmp_path: Path, status_code: int, body: bytes
    ) -> None:
        calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status_code,
                stream=_ChunkStream([body]),
                headers={"content-type": "application/json", "retry-after": "3"},
            )

        client, token, ledger = _gateway_client(
            tmp_path, upstream, capture_bodies=False
        )
        try:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-requested"},
            )
        finally:
            await client.aclose()

        assert response.status_code == status_code
        assert response.content == body
        assert response.headers["retry-after"] == "3"
        assert calls == 1
        assert ledger.read_all()[0].status_code == status_code

    async def test_replaces_x_api_key_with_zai_bearer(self, tmp_path: Path) -> None:
        observed_authorization = ""

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal observed_authorization
            observed_authorization = request.headers["authorization"]
            assert "x-api-key" not in request.headers
            return httpx.Response(204, stream=_ChunkStream([]))

        client, token, _ = _gateway_client(
            tmp_path,
            upstream,
            provider=ProviderBinding.ZAI_HARNESS,
            capture_bodies=False,
        )
        try:
            response = await client.get("/v1/models", headers={"x-api-key": token})
        finally:
            await client.aclose()

        assert response.status_code == 204
        assert observed_authorization == "Bearer real-zai-key"

    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    async def test_bodyless_methods_do_not_gain_chunked_framing(
        self, tmp_path: Path, method: str
    ) -> None:
        observed_headers = httpx.Headers()
        observed_body = b"unexpected"

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal observed_headers, observed_body
            observed_headers = request.headers
            observed_body = await request.aread()
            return httpx.Response(204, stream=_ChunkStream([]))

        client, token, _ = _gateway_client(tmp_path, upstream, capture_bodies=False)
        try:
            response = await client.send(
                httpx.Request(
                    method,
                    "http://gateway.test/v1/models",
                    headers={"x-api-key": token},
                )
            )
        finally:
            await client.aclose()

        assert response.status_code == 204
        assert observed_body == b""
        assert "transfer-encoding" not in observed_headers
        assert "content-length" not in observed_headers
        assert "accept" not in observed_headers
        assert "accept-encoding" not in observed_headers
        assert "user-agent" not in observed_headers

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"authorization": "Basic abc"},
            {"authorization": "Bearer unknown"},
            {"x-api-key": "unknown"},
        ],
    )
    async def test_rejects_missing_or_invalid_credentials_before_upstream(
        self, tmp_path: Path, headers: dict[str, str]
    ) -> None:
        calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200)

        client, _, ledger = _gateway_client(tmp_path, upstream)
        try:
            response = await client.get("/v1/models", headers=headers)
        finally:
            await client.aclose()

        assert response.status_code == 401
        assert calls == 0
        assert ledger.read_all() == []

    async def test_rejects_ambiguous_dual_credentials(self, tmp_path: Path) -> None:
        async def upstream(_: httpx.Request) -> httpx.Response:
            raise AssertionError("upstream must not be called")

        client, token, _ = _gateway_client(tmp_path, upstream)
        try:
            response = await client.get(
                "/v1/models",
                headers=[
                    ("authorization", f"Bearer {token}"),
                    ("x-api-key", token),
                ],
            )
        finally:
            await client.aclose()

        assert response.status_code == 401

    async def test_connect_failure_is_single_attempt_and_ledgered_502(
        self, tmp_path: Path
    ) -> None:
        calls = 0

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("offline", request=request)

        client, token, ledger = _gateway_client(
            tmp_path, upstream, capture_bodies=False
        )
        try:
            response = await client.post(
                "/v1/messages",
                headers={"authorization": f"Bearer {token}"},
                json={"model": "claude-requested"},
            )
        finally:
            await client.aclose()

        assert response.status_code == 502
        assert response.json() == {"detail": "upstream unavailable"}
        assert calls == 1
        row = ledger.read_all()[0]
        assert row.status_code == 502
        assert row.completed is False
        assert row.status == "upstream-error"
        assert row.cost_usd is None
        assert row.cost_unknown is True

    async def test_unknown_model_cost_is_null_and_explicitly_unknown(
        self, tmp_path: Path
    ) -> None:
        unknown_sse = _SSE_BYTES.replace(b"claude-sonnet-4-6", b"future-model-99")

        async def upstream(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_ChunkStream([unknown_sse]))

        client, token, ledger = _gateway_client(
            tmp_path, upstream, capture_bodies=False
        )
        try:
            response = await client.post(
                "/v1/messages",
                headers={"authorization": f"Bearer {token}"},
                json={"model": "future-model-99"},
            )
        finally:
            await client.aclose()

        assert response.status_code == 200
        row = ledger.read_all()[0]
        assert row.model_served == "future-model-99"
        assert row.usage_complete is True
        assert row.cost_usd is None
        assert row.cost_unknown is True

    async def test_zai_shaped_stream_is_priced_exclusive_with_attribution(
        self, tmp_path: Path
    ) -> None:
        async def upstream(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_ChunkStream([_ZAI_SSE_BYTES[:40], _ZAI_SSE_BYTES[40:]]),
            )

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            provider=ProviderBinding.ZAI_HARNESS,
            capture_bodies=False,
            issue_number=11464,
            pr_number=11500,
        )
        try:
            response = await client.post(
                "/v1/messages?beta=true",
                headers={"authorization": f"Bearer {token}"},
                json={"model": "glm-5.2", "messages": []},
            )
        finally:
            await client.aclose()

        assert response.status_code == 200
        assert response.content == _ZAI_SSE_BYTES
        (row,) = ledger.read_all()
        assert row.upstream_provider == "zai-harness"
        assert row.model_requested == "glm-5.2"
        assert row.model_served == "glm-5.3"
        assert row.input_tokens == 1244
        assert row.output_tokens == 532
        assert row.cache_read_input_tokens == 46784
        assert row.cache_creation_input_tokens == 0
        assert row.usage_complete is True
        assert row.cost_unknown is False
        assert row.cost_usd == pytest.approx(_ZAI_EXPECTED_COST)
        assert row.path == "/v1/messages"
        assert row.principal.issue_number == 11464
        assert row.principal.pr_number == 11500
        assert row.to_json_dict()["principal"]["pr_number"] == 11500

    @pytest.mark.parametrize(
        "first_event, partial_input_tokens",
        [
            pytest.param(
                _ZAI_SSE_BYTES.split(b"\n\n", 1)[0] + b"\n\n", 0, id="zai-empty-usage"
            ),
            pytest.param(
                _SSE_BYTES.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n",
                11,
                id="anthropic-partial-usage",
            ),
        ],
    )
    async def test_client_abort_after_message_start_is_incomplete_and_cost_unknown(
        self, tmp_path: Path, first_event: bytes, partial_input_tokens: int
    ) -> None:
        first_body_sent = asyncio.Event()
        upstream_stream = _BlockingStream(first_event)
        request_messages: list[Message] = [
            {
                "type": "http.request",
                "body": b'{"model":"glm-5.2"}',
                "more_body": False,
            }
        ]

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=upstream_stream)

        async def receive() -> Message:
            if request_messages:
                return request_messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                first_body_sent.set()

        request = _streaming_request(receive)
        proxy, identity, ledger, upstream_client = _direct_gateway_proxy(
            tmp_path, upstream
        )
        try:
            response = await proxy.forward(request, identity)
            response_task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(first_body_sent.wait(), timeout=1)
            response_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await response_task
        finally:
            await upstream_client.aclose()

        (row,) = ledger.read_all()
        assert row.status == "client-aborted"
        assert row.status_code == 499
        assert row.client_aborted is True
        assert row.completed is False
        assert row.model_served is not None
        assert row.input_tokens == partial_input_tokens
        assert row.usage_complete is False
        assert row.cost_usd is None
        assert row.cost_unknown is True
        assert row.path == "/v1/messages"
        assert upstream_stream.closed is True

    @pytest.mark.parametrize("repo_class", [RepoClass.CLIENT, RepoClass.PERSONAL])
    async def test_sensitive_repo_request_never_creates_body_artifacts(
        self, tmp_path: Path, repo_class: RepoClass
    ) -> None:
        async def upstream(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_ChunkStream([b"ok"]))

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=False,
            repo_class=repo_class,
        )
        try:
            response = await client.post(
                "/v1/messages", headers={"x-api-key": token}, content=b"request"
            )
        finally:
            await client.aclose()

        assert response.content == b"ok"
        assert ledger.read_all()[0].body_capture_id is None
        assert not (tmp_path / "bodies").exists()

    async def test_declared_oversized_request_is_rejected_before_upstream(
        self, tmp_path: Path
    ) -> None:
        calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=_ChunkStream([]))

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=True,
            max_request_bytes=4,
        )
        try:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=b"12345",
            )
        finally:
            await client.aclose()

        assert response.status_code == 413
        assert calls == 0
        rows = ledger.read_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status_code == 413
        assert row.completed is False
        assert row.status == "upstream-error"
        assert row.body_capture_id is None
        assert row.body_capture_complete is None
        assert not (tmp_path / "bodies").exists()

    async def test_invalid_upstream_path_is_ledgered_without_capture_leak(
        self, tmp_path: Path
    ) -> None:
        calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=_ChunkStream([]))

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=True,
        )
        try:
            response = await client.get(
                "/v1/%252e%252e/admin",
                headers={"x-api-key": token},
            )
        finally:
            await client.aclose()

        assert response.status_code == 400
        assert response.json() == {"detail": "invalid upstream path"}
        assert calls == 0
        rows = ledger.read_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status_code == 400
        assert row.completed is False
        assert row.status == "upstream-error"
        assert row.body_capture_id is None
        assert row.body_capture_complete is None
        assert not (tmp_path / "bodies").exists()

    async def test_body_capture_failure_latches_and_ledgers_next_503(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = 0
        capture_start_calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=_ChunkStream([]))

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=True,
        )

        def capture_unavailable(*_: object) -> None:
            nonlocal capture_start_calls
            capture_start_calls += 1
            raise OSError("capture store unavailable")

        monkeypatch.setattr(GatewayBodyStore, "start", capture_unavailable)
        try:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=b'{"model":"claude-requested"}',
            )
            health = await client.get("/healthz")
            latched = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=b'{"model":"claude-requested"}',
            )
        finally:
            await client.aclose()

        assert response.status_code == 503
        assert response.json() == {
            "detail": "gateway observation storage is unavailable"
        }
        assert latched.status_code == 503
        assert latched.json() == {
            "detail": "gateway observation storage is unavailable"
        }
        assert calls == 0
        rows = ledger.read_all()
        assert len(rows) == 2
        row = rows[0]
        assert row.status_code == 503
        assert row.completed is False
        assert row.status == "upstream-error"
        assert row.body_capture_id is None
        assert row.body_capture_complete is None
        assert row.cost_usd is None
        assert row.cost_unknown is True
        latched_row = rows[1]
        assert latched_row.status_code == 503
        assert latched_row.status == "upstream-error"
        assert latched_row.completed is False
        assert latched_row.client_aborted is False
        assert latched_row.body_capture_id is None
        assert latched_row.body_capture_complete is None
        assert latched_row.request_id != row.request_id
        assert capture_start_calls == 1
        assert health.status_code == 503
        assert not (tmp_path / "bodies").exists()

    @pytest.mark.parametrize(
        ("failure_boundary", "captured_request", "captured_response"),
        [
            ("write_request", b"", b""),
            ("write_response", b'{"model":"claude-requested"}', b""),
            (
                "close",
                b'{"model":"claude-requested"}',
                b"response-\x00\xff-bytes",
            ),
        ],
        ids=["write-request", "write-response", "close"],
    )
    async def test_started_body_capture_persistence_failure_preserves_bytes_and_latches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        failure_boundary: str,
        captured_request: bytes,
        captured_response: bytes,
    ) -> None:
        upstream_calls = 0
        failure_calls = 0
        observed_request_body = b""
        request_body = b'{"model":"claude-requested"}'
        response_body = b"response-\x00\xff-bytes"
        original_close = GatewayBodyCapture.close

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal observed_request_body, upstream_calls
            upstream_calls += 1
            observed_request_body = await request.aread()
            return httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                stream=_ChunkStream([response_body[:10], response_body[10:]]),
            )

        def persistence_failure(
            capture: GatewayBodyCapture, _: bytes | None = None
        ) -> None:
            nonlocal failure_calls
            failure_calls += 1
            if failure_boundary == "close":
                original_close(capture)
            raise OSError(f"{failure_boundary} persistence failure")

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=True,
        )
        monkeypatch.setattr(
            GatewayBodyCapture,
            failure_boundary,
            persistence_failure,
        )
        try:
            first = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=request_body,
            )

            first_rows = ledger.read_all()
            assert len(first_rows) == 1
            first_row = first_rows[0]
            assert first_row.status_code == 200
            assert first_row.status == "completed"
            assert first_row.completed is True
            assert first_row.client_aborted is False
            assert first_row.body_capture_id is not None
            assert first_row.body_capture_complete is False
            assert (
                tmp_path / "bodies" / f"{first_row.body_capture_id}.request.body"
            ).read_bytes() == captured_request
            assert (
                tmp_path / "bodies" / f"{first_row.body_capture_id}.response.body"
            ).read_bytes() == captured_response

            health = await client.get("/healthz")
            second = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=b"must-not-reach-upstream",
            )
        finally:
            await client.aclose()

        assert first.content == response_body
        assert observed_request_body == request_body
        assert health.status_code == 503
        assert health.json()["status"] == "degraded"
        assert second.status_code == 503
        assert second.json() == {"detail": "gateway observation storage is unavailable"}
        assert upstream_calls == 1
        assert failure_calls == 1

        rows = ledger.read_all()
        assert len(rows) == 2
        assert rows[0] == first_row
        latched_row = rows[1]
        assert latched_row.request_id != first_row.request_id
        assert latched_row.status_code == 503
        assert latched_row.status == "upstream-error"
        assert latched_row.completed is False
        assert latched_row.client_aborted is False
        assert latched_row.body_capture_id is None
        assert latched_row.body_capture_complete is None

    async def test_chunked_request_is_stopped_at_streamed_size_limit(
        self, tmp_path: Path
    ) -> None:
        calls = 0

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            await request.aread()
            return httpx.Response(204, stream=_ChunkStream([]))

        async def chunks() -> AsyncIterator[bytes]:
            yield b"12"
            yield b"345"

        client, token, ledger = _gateway_client(
            tmp_path,
            upstream,
            capture_bodies=False,
            max_request_bytes=4,
        )
        try:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                content=chunks(),
            )
        finally:
            await client.aclose()

        assert response.status_code == 413
        assert calls == 0
        row = ledger.read_all()[0]
        assert row.status_code == 413
        assert row.completed is False

    async def test_cancellation_before_first_request_chunk_finalizes_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream_calls = 0
        capture_close_calls = 0
        receive_started = asyncio.Event()
        never_receive = asyncio.Event()
        original_close = GatewayBodyCapture.close

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            return httpx.Response(200, stream=_ChunkStream([]))

        async def receive() -> Message:
            receive_started.set()
            await never_receive.wait()
            return {"type": "http.disconnect"}

        def counted_close(capture: GatewayBodyCapture) -> None:
            nonlocal capture_close_calls
            capture_close_calls += 1
            original_close(capture)

        monkeypatch.setattr(GatewayBodyCapture, "close", counted_close)
        proxy, identity, ledger, upstream_client = _direct_gateway_proxy(
            tmp_path, upstream
        )
        task = asyncio.create_task(proxy.forward(_streaming_request(receive), identity))
        try:
            await asyncio.wait_for(receive_started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await upstream_client.aclose()

        rows = ledger.read_all()
        assert len(rows) == 1
        assert rows[0].status_code == 499
        assert rows[0].status == "client-aborted"
        assert rows[0].client_aborted is True
        assert rows[0].completed is False
        assert rows[0].body_capture_complete is True
        assert upstream_calls == 0
        assert capture_close_calls == 1
        assert [
            path.read_bytes() for path in sorted((tmp_path / "bodies").glob("*"))
        ] == [
            b"",
            b"",
        ]

    async def test_cancellation_during_upstream_upload_finalizes_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream_calls = 0
        capture_close_calls = 0
        receive_calls = 0
        upload_blocked = asyncio.Event()
        never_receive = asyncio.Event()
        original_close = GatewayBodyCapture.close
        first_chunk = b'{"model":"claude-sonnet-4-6",'

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.aread()
            return httpx.Response(200, stream=_ChunkStream([]))

        async def receive() -> Message:
            nonlocal receive_calls
            receive_calls += 1
            if receive_calls == 1:
                return {
                    "type": "http.request",
                    "body": first_chunk,
                    "more_body": True,
                }
            upload_blocked.set()
            await never_receive.wait()
            return {"type": "http.disconnect"}

        def counted_close(capture: GatewayBodyCapture) -> None:
            nonlocal capture_close_calls
            capture_close_calls += 1
            original_close(capture)

        monkeypatch.setattr(GatewayBodyCapture, "close", counted_close)
        proxy, identity, ledger, upstream_client = _direct_gateway_proxy(
            tmp_path, upstream
        )
        task = asyncio.create_task(proxy.forward(_streaming_request(receive), identity))
        try:
            await asyncio.wait_for(upload_blocked.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await upstream_client.aclose()

        rows = ledger.read_all()
        assert len(rows) == 1
        assert rows[0].status_code == 499
        assert rows[0].status == "client-aborted"
        assert rows[0].client_aborted is True
        assert rows[0].completed is False
        assert rows[0].body_capture_complete is True
        assert upstream_calls == 0
        assert capture_close_calls == 1
        captured_bodies = {
            path.name: path.read_bytes() for path in (tmp_path / "bodies").glob("*")
        }
        assert captured_bodies == {
            "request-1.request.body": first_chunk,
            "request-1.response.body": b"",
        }

    async def test_cancellation_after_upstream_headers_closes_unstarted_response(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capture_close_calls = 0
        response_start_sent = asyncio.Event()
        block_response_start = asyncio.Event()
        original_close = GatewayBodyCapture.close
        upstream_stream = _ChunkStream([b"must-not-be-consumed"])
        request_messages: list[Message] = [
            {
                "type": "http.request",
                "body": b'{"model":"claude-sonnet-4-6"}',
                "more_body": False,
            }
        ]

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=upstream_stream)

        async def receive() -> Message:
            if request_messages:
                return request_messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_start_sent.set()
                await block_response_start.wait()

        def counted_close(capture: GatewayBodyCapture) -> None:
            nonlocal capture_close_calls
            capture_close_calls += 1
            original_close(capture)

        monkeypatch.setattr(GatewayBodyCapture, "close", counted_close)
        request = _streaming_request(receive)
        proxy, identity, ledger, upstream_client = _direct_gateway_proxy(
            tmp_path, upstream
        )
        try:
            response = await proxy.forward(request, identity)
            response_task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(response_start_sent.wait(), timeout=1)
            response_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await response_task
        finally:
            await upstream_client.aclose()

        rows = ledger.read_all()
        assert len(rows) == 1
        assert rows[0].status_code == 499
        assert rows[0].status == "client-aborted"
        assert rows[0].client_aborted is True
        assert rows[0].completed is False
        assert rows[0].body_capture_complete is True
        assert upstream_stream.closed is True
        assert capture_close_calls == 1
        captured_bodies = {
            path.name: path.read_bytes() for path in (tmp_path / "bodies").glob("*")
        }
        assert captured_bodies == {
            "request-1.request.body": b'{"model":"claude-sonnet-4-6"}',
            "request-1.response.body": b"",
        }

    async def test_ledger_failure_does_not_break_started_response_and_fails_future(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = 0

        async def upstream(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=_ChunkStream([b"response-bytes"]))

        client, token, ledger = _gateway_client(
            tmp_path, upstream, capture_bodies=False
        )

        def disk_full(_: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(ledger, "append", disk_full)
        try:
            first = await client.post(
                "/v1/messages", headers={"x-api-key": token}, content=b"{}"
            )
            health = await client.get("/healthz")
            second = await client.post(
                "/v1/messages", headers={"x-api-key": token}, content=b"{}"
            )
        finally:
            await client.aclose()

        assert first.status_code == 200
        assert first.content == b"response-bytes"
        assert health.status_code == 503
        assert health.json()["status"] == "degraded"
        assert second.status_code == 503
        assert calls == 1


@pytest.mark.parametrize(
    "raw_path",
    [
        b"/a/../admin",
        b"/a/%2e%2e/admin",
        b"/a/%252e%252e/admin",
        b"/a/%2e%2e%2fadmin",
        b"/a/%2e%2e%5cadmin",
    ],
)
def test_build_upstream_url_rejects_decoded_dot_segments(raw_path: bytes) -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": raw_path.decode("ascii"),
            "raw_path": raw_path,
            "query_string": b"",
            "headers": [],
            "server": ("gateway.test", 80),
            "client": ("127.0.0.1", 12345),
        }
    )

    with pytest.raises(HTTPException, match="invalid upstream path"):
        build_upstream_url("https://upstream.test/prefix", request)


def test_sanitized_request_path_strips_query_and_bounds_length() -> None:
    long_path = "/v1/" + "a" * 5000
    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": long_path,
            "raw_path": long_path.encode(),
            "query_string": b"x=1&secret=must-not-surface",
            "headers": [],
            "server": ("gateway.test", 80),
            "client": ("127.0.0.1", 12345),
        },
    )

    path = sanitized_request_path(Request(scope))

    assert "must-not-surface" not in path
    assert "?" not in path
    assert len(path) == 2048
    assert path.startswith("/v1/aaaa")


# --------------------------------------------------------------------------
# ADR-0141: a route-bound key reaches its bound model, or no upstream at all
# --------------------------------------------------------------------------

_BOUND_MODEL = "glm-5.3"


def _governed_client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    governed_repo_slugs: frozenset[str] = frozenset(),
    bind_route: bool = True,
    capture_bodies: bool = False,
    max_request_bytes: int = 33_554_432,
) -> tuple[httpx.AsyncClient, str]:
    """A gateway holding one key, route-bound or deliberately not."""
    settings = _settings(tmp_path, max_request_bytes=max_request_bytes).model_copy(
        update={"governed_repo_slugs": governed_repo_slugs}
    )
    store = VirtualKeyStore(
        max_ttl_seconds=600,
        id_factory=lambda: "key-1",
        secret_factory=lambda: "virtual-secret",
        body_capture_repo_slugs=frozenset({"acme-hydraflow"}),
    )
    if bind_route:
        minted = store.mint_bound(
            principal=Principal(kind="spawn", id="implementer", spawn_id="spawn-1"),
            repo_slug="acme-hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ZAI_HARNESS,
            capture_bodies=capture_bodies,
            ttl_seconds=300,
            route_binding=RouteBinding(
                mint_decision_id="gwd_1",
                route_decision_id="dec_1",
                dispatch_id="disp-1",
                account_id="legacy-zai-harness",
                effective_model=_BOUND_MODEL,
                policy_id="project-x-zai",
                policy_revision=3,
            ),
        )
    else:
        minted = store.mint(
            MintKeyRequest(
                principal_kind="spawn",
                principal_id="implementer",
                spawn_id="spawn-1",
                repo_slug="acme-hydraflow",
                repo_class=RepoClass.HYDRAFLOW,
                provider_binding=ProviderBinding.ZAI_HARNESS,
                capture_bodies=False,
                ttl_seconds=300,
            )
        )
    app = create_app(
        settings,
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
    )
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ),
        minted.token,
    )


class TestGovernedDataPlane:
    """Every refusal here must leave the fake origin with nothing recorded."""

    @staticmethod
    def _origin() -> tuple[list[bytes], Callable[..., Any]]:
        seen: list[bytes] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(await request.aread())
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_ChunkStream([_ZAI_SSE_BYTES]),
            )

        return seen, handler

    async def _post(
        self,
        tmp_path: Path,
        *,
        path: str = "/v1/messages",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        governed_repo_slugs: frozenset[str] = frozenset(),
        bind_route: bool = True,
    ) -> tuple[int, list[bytes]]:
        seen, handler = self._origin()
        client, token = _governed_client(
            tmp_path,
            handler,
            governed_repo_slugs=governed_repo_slugs,
            bind_route=bind_route,
        )
        async with client:
            response = await client.post(
                path,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    **(headers or {}),
                },
                json=body if body is not None else {"model": _BOUND_MODEL},
            )
        return response.status_code, seen

    async def test_a_body_naming_the_bound_model_is_forwarded(
        self, tmp_path: Path
    ) -> None:
        """The affirmative case: a governed key still serves its own route."""
        status, _ = await self._post(tmp_path)

        assert status == 200

    async def test_the_forwarded_body_reaches_the_upstream_intact(
        self, tmp_path: Path
    ) -> None:
        """Buffering for the binding check must not drop or rewrite the bytes."""
        _, seen = await self._post(tmp_path, body={"model": _BOUND_MODEL, "x": 1})

        assert json.loads(seen[0]) == {"model": _BOUND_MODEL, "x": 1}

    @pytest.mark.parametrize(
        ("kwargs", "expected_status"),
        [
            pytest.param(
                {"body": {"model": "claude-opus-4-8"}},
                409,
                id="a-body-naming-another-model-is-refused",
            ),
            pytest.param(
                {"body": {"messages": []}},
                409,
                id="a-body-naming-no-model-is-refused",
            ),
            pytest.param(
                {"path": "/v1/models"},
                403,
                id="an-unenumerated-face-is-refused",
            ),
            pytest.param(
                {
                    "governed_repo_slugs": frozenset({"acme-hydraflow"}),
                    "bind_route": False,
                },
                403,
                id="an-unbound-key-for-a-governed-repository-is-refused",
            ),
            pytest.param(
                {
                    # The operator wrote the canonical form; the caller sends
                    # the slug. ADR-0141 §D4: the set is owned by the
                    # deployment and cannot be asserted by the caller, so a
                    # spelling difference must not open the boundary.
                    "governed_repo_slugs": frozenset({"acme/hydraflow"}),
                    "bind_route": False,
                },
                403,
                id="the-callers-spelling-cannot-escape-the-governed-set",
            ),
        ],
    )
    async def test_a_request_that_defeats_the_binding_is_refused(
        self, tmp_path: Path, kwargs: dict[str, Any], expected_status: int
    ) -> None:
        """Each refusal carries its own status, never a shared generic error."""
        status, _ = await self._post(tmp_path, **kwargs)

        assert status == expected_status

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"body": {"model": "claude-opus-4-8"}}, id="a-model-mismatch"),
            pytest.param({"body": {"messages": []}}, id="a-missing-model"),
            pytest.param({"path": "/v1/models"}, id="an-unenumerated-face"),
            pytest.param(
                {
                    "governed_repo_slugs": frozenset({"acme-hydraflow"}),
                    "bind_route": False,
                },
                id="an-unbound-key-for-a-governed-repository",
            ),
        ],
    )
    async def test_a_refused_request_sends_zero_upstream_bytes(
        self, tmp_path: Path, kwargs: dict[str, Any]
    ) -> None:
        """The property the whole enforcement claim rests on."""
        _, seen = await self._post(tmp_path, **kwargs)

        assert seen == []

    async def test_a_refused_request_names_its_reason_on_the_durable_row(
        self, tmp_path: Path
    ) -> None:
        """A 409 an operator cannot classify afterwards is a 409 they cannot fix."""
        seen, handler = self._origin()
        settings = _settings(tmp_path)
        client, token = _governed_client(tmp_path, handler)
        async with client:
            await client.post(
                "/v1/messages",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"model": "claude-opus-4-8"},
            )
        rows = GatewayLedger(settings.ledger_path).read_all()

        assert [row.refusal_reason for row in rows] == ["model-not-bound"]

    async def test_a_served_request_names_no_refusal(self, tmp_path: Path) -> None:
        """The column is null for everything that was not refused."""
        seen, handler = self._origin()
        settings = _settings(tmp_path)
        client, token = _governed_client(tmp_path, handler)
        async with client:
            await client.post(
                "/v1/messages",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"model": _BOUND_MODEL},
            )
        rows = GatewayLedger(settings.ledger_path).read_all()

        assert [row.refusal_reason for row in rows] == [None]

    async def test_a_refused_request_does_not_claim_a_complete_capture(
        self, tmp_path: Path
    ) -> None:
        """The capture was opened before the body was read, and never written."""
        seen, handler = self._origin()
        settings = _settings(tmp_path)
        client, token = _governed_client(tmp_path, handler, capture_bodies=True)
        async with client:
            await client.post(
                "/v1/messages",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"model": "claude-opus-4-8"},
            )
        rows = GatewayLedger(settings.ledger_path).read_all()

        assert [row.body_capture_complete for row in rows] == [False]

    async def test_a_governed_body_over_the_ceiling_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The buffered path must honour the same bound the streamed one does."""
        seen, handler = self._origin()
        client, token = _governed_client(tmp_path, handler, max_request_bytes=256)
        async with client:
            response = await client.post(
                "/v1/messages",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"model": _BOUND_MODEL, "padding": "x" * 4096},
            )

        assert response.status_code == 413

    async def test_an_oversized_governed_body_sends_zero_upstream_bytes(
        self, tmp_path: Path
    ) -> None:
        """Refused for size is still refused before an upstream request exists."""
        seen, handler = self._origin()
        client, token = _governed_client(tmp_path, handler, max_request_bytes=256)
        async with client:
            await client.post(
                "/v1/messages",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                },
                json={"model": _BOUND_MODEL, "padding": "x" * 4096},
            )

        assert seen == []


async def test_a_bound_key_whose_account_has_no_upstream_fails_closed(
    tmp_path: Path,
) -> None:
    """ADR-0142: never serve a bound key on another account's credential.

    Falling back to the lane's upstream would make the request *succeed* — and
    put the spend on an account no decision ever named, which is precisely the
    misattribution an immutable account binding exists to prevent. The honest
    answer is 503.
    """
    reached: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        return httpx.Response(200)

    settings = _settings(tmp_path)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint_bound(
        principal=Principal(kind="spawn", id="implementer", spawn_id="spawn-1"),
        repo_slug="acme-hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        provider_binding=ProviderBinding.ZAI_HARNESS,
        capture_bodies=False,
        ttl_seconds=600,
        route_binding=RouteBinding(
            mint_decision_id="gwd_orphan",
            route_decision_id="dec_orphan",
            dispatch_id="disp-1",
            # In the registry, but this process resolved no credential for it.
            account_id="zai-secondary",
            effective_model="glm-5.3",
        ),
    )
    identity = store.resolve(minted.token)
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        account_pool=load_account_pool(settings, {}),
        request_id_factory=lambda: "request-orphan",
    )

    async def receive() -> Message:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    try:
        with pytest.raises(HTTPException) as excinfo:
            await proxy.forward(_streaming_request(receive), identity)
    finally:
        await upstream_client.aclose()

    assert (excinfo.value.status_code, reached) == (503, [])


async def test_a_poolless_proxy_still_serves_a_legacy_bound_key(
    tmp_path: Path,
) -> None:
    """The lane IS the account for a reserved legacy id, so this is not a guess.

    The sibling test above pins the other half: a *declared* account with no
    pool wired resolves to nothing rather than to the lane's credential.
    """
    reached: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkStream([b"data: {}\n\n"]),
        )

    settings = _settings(tmp_path)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint_bound(
        principal=Principal(kind="spawn", id="implementer", spawn_id="spawn-1"),
        repo_slug="acme-hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        provider_binding=ProviderBinding.ZAI_HARNESS,
        capture_bodies=False,
        ttl_seconds=600,
        route_binding=RouteBinding(
            mint_decision_id="gwd_legacy",
            route_decision_id="dec_legacy",
            dispatch_id="disp-1",
            account_id=legacy_account_id(ProviderBinding.ZAI_HARNESS),
            effective_model="glm-5.3",
        ),
    )
    identity = store.resolve(minted.token)
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        request_id_factory=lambda: "request-legacy",
    )

    async def receive() -> Message:
        return {
            "type": "http.request",
            "body": b'{"model":"glm-5.3"}',
            "more_body": False,
        }

    try:
        response = await proxy.forward(_streaming_request(receive), identity)
        async for _chunk in response.body_iterator:
            pass
    finally:
        await upstream_client.aclose()

    assert reached == ["https://zai.test/v1/messages"]


async def test_a_poolless_proxy_refuses_a_declared_bound_key(tmp_path: Path) -> None:
    """A declared account this proxy cannot reach is a 503, never the lane's key."""
    reached: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        return httpx.Response(200)

    settings = _settings(tmp_path)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint_bound(
        principal=Principal(kind="spawn", id="implementer", spawn_id="spawn-1"),
        repo_slug="acme-hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        provider_binding=ProviderBinding.ZAI_HARNESS,
        capture_bodies=False,
        ttl_seconds=600,
        route_binding=RouteBinding(
            mint_decision_id="gwd_declared",
            route_decision_id="dec_declared",
            dispatch_id="disp-1",
            account_id="zai-secondary",
            effective_model="glm-5.3",
        ),
    )
    identity = store.resolve(minted.token)
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        request_id_factory=lambda: "request-declared",
    )

    async def receive() -> Message:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    try:
        with pytest.raises(HTTPException) as excinfo:
            await proxy.forward(_streaming_request(receive), identity)
    finally:
        await upstream_client.aclose()

    assert (excinfo.value.status_code, reached) == (503, [])

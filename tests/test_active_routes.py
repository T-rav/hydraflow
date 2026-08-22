"""``hydraflow_gateway.active_routes`` — registered on accept, cleared on every
terminal path.

ADR-0138. Named for the module it covers (the P10.2 unit-ring rule), not for the
``test_gateway_*`` grouping the rest of the gateway suite uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Message, Receive, Scope

from hydraflow_gateway.active_routes import (
    DEFAULT_RECENT_CAPACITY,
    ActiveRouteRegistry,
    build_active_routes_view,
)
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger, GatewayLedgerRow
from hydraflow_gateway.models import (
    GatewayIdentity,
    GatewayRequestStatus,
    MintKeyRequest,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.proxy import GatewayProxy
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from model_pricing import load_pricing

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_SSE_BYTES = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"glm-5.3","usage":{}}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","usage":'
    b'{"input_tokens":10,"output_tokens":5}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


class _BlockingStream(httpx.AsyncByteStream):
    """Yield one chunk, then block until closed — a stream the client abandons."""

    def __init__(self, first_chunk: bytes) -> None:
        self._first_chunk = first_chunk
        self._released = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._first_chunk
        await self._released.wait()

    async def aclose(self) -> None:
        self._released.set()


def _settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test",
                api_key=SecretStr("real-anthropic-key"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _identity(store: VirtualKeyStore) -> GatewayIdentity:
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            issue_number=11534,
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    return store.resolve(minted.token)


def _proxy(
    tmp_path: Path,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> tuple[GatewayProxy, GatewayIdentity, ActiveRouteRegistry, httpx.AsyncClient]:
    settings = _settings(tmp_path)
    store = VirtualKeyStore(
        max_ttl_seconds=600,
        id_factory=lambda: "key-1",
        secret_factory=lambda: "virtual-secret",
    )
    identity = _identity(store)
    registry = ActiveRouteRegistry(started_at=_NOW)
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        active_routes=registry,
        request_id_factory=lambda: "request-1",
    )
    return proxy, identity, registry, upstream_client


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


def _request_messages() -> list[Message]:
    return [
        {"type": "http.request", "body": b'{"model":"glm-5.2"}', "more_body": False}
    ]


def _receiver(messages: list[Message]) -> Receive:
    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    return receive


def _row(
    *,
    request_id: str = "request-1",
    status: GatewayRequestStatus = GatewayRequestStatus.COMPLETED,
) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal={"kind": "spawn", "id": "implementer", "spawn_id": "spawn-1"},
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="metadata-only",
        timestamp=_NOW,
        latency_ms=12.0,
        status_code=200,
        status=status,
        upstream_provider=ProviderBinding.ANTHROPIC,
        path="/v1/messages",
        model_requested="glm-5.2",
        model_served="glm-5.3",
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.0,
        cost_unknown=False,
    )


def _registered(
    registry: ActiveRouteRegistry, *, request_id: str = "request-1"
) -> None:
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: request_id)
    registry.register(
        request_id=request_id,
        identity=_identity(store),
        path="/v1/messages",
        started_at=_NOW,
    )


class TestRegistryLifecycle:
    def test_register_records_one_in_flight_route(self) -> None:
        """An accepted request is visible while it streams."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)

        assert len(registry.in_flight()) == 1

    def test_release_clears_the_in_flight_route(self) -> None:
        """Finalizing removes the row; nothing lingers as phantom traffic."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)

        registry.release(_row())

        assert registry.in_flight() == ()

    def test_release_retains_the_route_as_recent_evidence(self) -> None:
        """The terminal ledger row is kept, bounded, as recent evidence."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)

        registry.release(_row())

        assert registry.recent()[0].request_id == "request-1"

    def test_releasing_an_unknown_request_records_nothing(self) -> None:
        """A double finalize cannot duplicate a recent row."""
        registry = ActiveRouteRegistry(started_at=_NOW)

        registry.release(_row())

        assert registry.recent() == ()

    def test_discard_clears_a_route_without_recording_evidence(self) -> None:
        """The fail-safe path clears the row when no terminal row could be built."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)

        registry.discard("request-1")

        assert (registry.in_flight(), registry.recent()) == ((), ())

    def test_discard_after_release_is_a_no_op(self) -> None:
        """Belt-and-braces must not erase the recent row release just recorded."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)
        registry.release(_row())

        registry.discard("request-1")

        assert len(registry.recent()) == 1

    def test_clear_drops_every_in_flight_route(self) -> None:
        """Shutdown ends every stream, so no in-flight row may survive it."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)

        registry.clear()

        assert registry.in_flight() == ()

    def test_recent_routes_are_newest_first(self) -> None:
        """The Live view reads top-down, so the newest terminal route leads."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        for index in range(3):
            _registered(registry, request_id=f"req-{index}")
            registry.release(_row(request_id=f"req-{index}"))

        assert registry.recent()[0].request_id == "req-2"

    def test_recent_evidence_is_bounded_by_its_ring(self) -> None:
        """Retention is capped so a long-lived gateway cannot grow without bound."""
        registry = ActiveRouteRegistry(started_at=_NOW, recent_capacity=2)
        for index in range(3):
            _registered(registry, request_id=f"req-{index}")
            registry.release(_row(request_id=f"req-{index}"))

        assert len(registry.recent()) == 2

    def test_eviction_is_reported_so_the_view_cannot_overclaim(self) -> None:
        """A truncated ring must announce itself rather than look complete."""
        registry = ActiveRouteRegistry(started_at=_NOW, recent_capacity=2)
        for index in range(3):
            _registered(registry, request_id=f"req-{index}")
            registry.release(_row(request_id=f"req-{index}"))

        assert registry.truncated() is True

    def test_an_unfilled_ring_is_not_truncated(self) -> None:
        """Nothing evicted means the recent view is complete for this process."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        _registered(registry)
        registry.release(_row())

        assert registry.truncated() is False

    def test_recent_honours_an_explicit_limit(self) -> None:
        """Read callers bound their own page size."""
        registry = ActiveRouteRegistry(started_at=_NOW)
        for index in range(3):
            _registered(registry, request_id=f"req-{index}")
            registry.release(_row(request_id=f"req-{index}"))

        assert len(registry.recent(limit=1)) == 1

    def test_default_capacity_is_bounded(self) -> None:
        """The default ring is small enough to stay a cache, not a history."""
        assert ActiveRouteRegistry().recent_capacity == DEFAULT_RECENT_CAPACITY

    def test_zero_capacity_is_rejected(self) -> None:
        """A ring that retains nothing would silently disable recent evidence."""
        with pytest.raises(ValueError, match="recent_capacity"):
            ActiveRouteRegistry(recent_capacity=0)


class TestProxyLifecycle:
    async def test_route_is_in_flight_while_the_response_streams(
        self, tmp_path: Path
    ) -> None:
        """The registry sees the request between upstream accept and finalize."""

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=_ChunkStream([_SSE_BYTES]))

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        try:
            request = _streaming_request(_receiver(_request_messages()))
            await proxy.forward(request, identity)

            assert len(registry.in_flight()) == 1
        finally:
            await upstream_client.aclose()

    async def test_successful_stream_clears_the_in_flight_route(
        self, tmp_path: Path
    ) -> None:
        """Success is a terminal path and must release the row."""

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=_ChunkStream([_SSE_BYTES]))

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        try:
            messages = _request_messages()
            receive = _receiver(messages)
            request = _streaming_request(receive)
            response = await proxy.forward(request, identity)

            async def send(_: Message) -> None:
                return None

            await response(request.scope, receive, send)
        finally:
            await upstream_client.aclose()

        assert registry.in_flight() == ()

    async def test_upstream_error_clears_the_in_flight_route(
        self, tmp_path: Path
    ) -> None:
        """A transport failure is a terminal path and must release the row."""

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            raise httpx.ConnectError("upstream down")

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        try:
            request = _streaming_request(_receiver(_request_messages()))
            with pytest.raises(Exception, match="upstream unavailable"):
                await proxy.forward(request, identity)
        finally:
            await upstream_client.aclose()

        assert registry.in_flight() == ()

    async def test_client_abort_clears_the_in_flight_route(
        self, tmp_path: Path
    ) -> None:
        """A cancelled response is a terminal path and must release the row."""
        first_body_sent = asyncio.Event()
        upstream_stream = _BlockingStream(_SSE_BYTES[:40])

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=upstream_stream)

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        try:
            messages = _request_messages()
            receive = _receiver(messages)
            request = _streaming_request(receive)

            async def send(message: Message) -> None:
                if message["type"] == "http.response.body" and message.get("body"):
                    first_body_sent.set()

            response = await proxy.forward(request, identity)
            response_task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(first_body_sent.wait(), timeout=1)
            response_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await response_task
        finally:
            await upstream_client.aclose()

        assert registry.in_flight() == ()

    async def test_telemetry_failure_clears_the_in_flight_route(
        self, tmp_path: Path
    ) -> None:
        """Failing closed on storage loss must not leave a phantom active row."""

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=_ChunkStream([_SSE_BYTES]))

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        proxy.mark_telemetry_unhealthy()
        try:
            request = _streaming_request(_receiver(_request_messages()))
            with pytest.raises(Exception, match="observation storage"):
                await proxy.forward(request, identity)
        finally:
            await upstream_client.aclose()

        assert registry.in_flight() == ()

    async def test_finalized_route_becomes_recent_evidence(
        self, tmp_path: Path
    ) -> None:
        """The served model reaches the Live view through the same terminal row."""

        async def upstream(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return httpx.Response(200, stream=_ChunkStream([_SSE_BYTES]))

        proxy, identity, registry, upstream_client = _proxy(tmp_path, upstream)
        try:
            messages = _request_messages()
            receive = _receiver(messages)
            request = _streaming_request(receive)
            response = await proxy.forward(request, identity)

            async def send(_: Message) -> None:
                return None

            await response(request.scope, receive, send)
        finally:
            await upstream_client.aclose()

        assert registry.recent()[0].model_served == "glm-5.3"


class TestViewAssembly:
    def test_lease_age_is_measured_from_issue_time(self) -> None:
        """The Live view shows lease age, so it must be derived, not invented."""
        store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
        view = build_active_routes_view(
            leases=[_identity(store)],
            in_flight=(),
            now=datetime.now(tz=UTC) + timedelta(seconds=30),
            evidence_since=_NOW,
        )

        assert view.leases[0].age_seconds >= 30

    def test_lease_carries_its_compiled_account_id(self) -> None:
        """Leases join to accounts by the same stable id the Accounts view uses."""
        store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
        view = build_active_routes_view(
            leases=[_identity(store)],
            in_flight=(),
            now=_NOW,
            evidence_since=_NOW,
        )

        assert view.leases[0].account_id == "legacy-anthropic"

"""Regression: a raise inside finalize must not leak a phantom in-flight route.

Issue #11534 / ADR-0138 D3. The first cut of the active-route registry released
the in-flight row from a ``finally`` that wrapped only ``self._ledger.append``.
Everything above it in ``GatewayProxy._finalize_attempt`` — the body-capture
close, the pricing lookup, and the ``GatewayLedgerRow`` construction itself —
ran outside that guard, and ``_GatewayAttempt.finalize`` sets ``finalized``
*before* delegating, so a raise on the way through was unrecoverable: the row
stayed registered for the process lifetime.

The trigger is real, not theoretical. ``GatewayLedgerRow.status_code`` is bounded
``0..599`` while h11 will parse any three-digit status line, so an upstream
answering ``999`` is enough to raise a ``ValidationError`` at exactly that point.
An operator would then see a permanently "streaming" request, a permanently
``in_flight`` account, and an ``age_seconds`` that grows without bound — the
precise falsehood the whole read plane exists to prevent.

``ActiveRouteRegistry.discard`` in a ``finally`` around the whole finalize path
is the fix; this pins it.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import httpx
from pydantic import SecretStr, ValidationError
from starlette.requests import Request
from starlette.types import Message, Receive, Scope

from hydraflow_gateway.active_routes import ActiveRouteRegistry
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import (
    GatewayIdentity,
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
_SSE_BYTES = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"glm-5.3","usage":{}}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _ChunkStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield _SSE_BYTES

    async def aclose(self) -> None:
        return None


def _identity(store: VirtualKeyStore) -> GatewayIdentity:
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    return store.resolve(minted.token)


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


async def test_an_unpersistable_terminal_row_still_clears_the_in_flight_route(
    tmp_path: Path,
) -> None:
    """An upstream status the ledger cannot model must not leave a phantom route."""
    settings = GatewaySettings(
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
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
    identity = _identity(store)
    registry = ActiveRouteRegistry()

    async def upstream(request: httpx.Request) -> httpx.Response:
        await request.aread()
        # Outside GatewayLedgerRow.status_code's 0..599 bound.
        return httpx.Response(999, stream=_ChunkStream())

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    proxy = GatewayProxy(
        settings=settings,
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
        pricing=load_pricing(),
        active_routes=registry,
        request_id_factory=lambda: "request-1",
    )
    messages: list[Message] = [
        {"type": "http.request", "body": b'{"model":"glm-5.2"}', "more_body": False}
    ]

    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(_: Message) -> None:
        return None

    try:
        request = _streaming_request(receive)
        response = await proxy.forward(request, identity)
        with contextlib.suppress(ValidationError):
            await response(request.scope, receive, send)
    finally:
        await upstream_client.aclose()

    assert registry.in_flight() == ()

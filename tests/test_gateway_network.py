"""Real-socket streaming and client-abort propagation tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import SecretStr
from starlette.responses import Response, StreamingResponse

from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayLedger
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_FIRST_EVENT = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":2}}}\n\n'
)
_LAST_EVENT = (
    b'event: message_delta\ndata: {"type":"message_delta","usage":'
    b'{"output_tokens":3}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"


@asynccontextmanager
async def _serve(app: Any) -> AsyncIterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            lifespan="on",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("uvicorn did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()


class TestGatewayNetworkStreaming:
    async def test_first_chunk_is_unbuffered_and_abort_closes_upstream(
        self, tmp_path: Path
    ) -> None:
        upstream_closed = asyncio.Event()
        release_upstream = asyncio.Event()
        upstream = FastAPI()

        @upstream.post("/v1/messages")
        async def messages(request: Request) -> StreamingResponse:
            if request.headers.get("x-api-key") != "provider-secret":
                raise HTTPException(status_code=401)
            await request.body()

            async def response_chunks() -> AsyncIterator[bytes]:
                completed = False
                try:
                    yield _FIRST_EVENT
                    await release_upstream.wait()
                    yield _LAST_EVENT
                    completed = True
                finally:
                    assert completed is False
                    upstream_closed.set()

            return StreamingResponse(response_chunks(), media_type="text/event-stream")

        async with _serve(upstream) as upstream_url:
            settings = GatewaySettings(
                control_token=SecretStr(_CONTROL_TOKEN),
                upstreams={
                    ProviderBinding.ANTHROPIC: UpstreamSettings(
                        base_url=upstream_url,
                        api_key=SecretStr("provider-secret"),
                        auth_style=UpstreamAuthStyle.X_API_KEY,
                    )
                },
                ledger_path=tmp_path / "gateway.jsonl",
                body_dir=tmp_path / "bodies",
            )
            store = VirtualKeyStore(max_ttl_seconds=300)
            minted = store.mint(
                MintKeyRequest(
                    principal_kind="spawn",
                    principal_id="implementer",
                    spawn_id="spawn-1",
                    repo_slug="acme/hydraflow",
                    repo_class="hydraflow",
                    provider_binding="anthropic",
                    capture_bodies=False,
                    ttl_seconds=60,
                )
            )
            gateway = create_app(settings, key_store=store)
            async with _serve(gateway) as gateway_url:
                async with (
                    httpx.AsyncClient(timeout=httpx.Timeout(5, read=2)) as client,
                    client.stream(
                        "POST",
                        f"{gateway_url}/v1/messages",
                        headers={
                            "authorization": f"Bearer {minted.token}",
                            "content-type": "application/json",
                        },
                        content=b'{"model":"claude-sonnet-4-6"}',
                    ) as response,
                ):
                    chunks = response.aiter_raw()
                    first = await anext(chunks)
                    assert response.status_code == 200
                    assert first == _FIRST_EVENT
                    assert release_upstream.is_set() is False

                await asyncio.wait_for(upstream_closed.wait(), timeout=2)
                ledger = GatewayLedger(settings.ledger_path)
                for _ in range(100):
                    rows = ledger.read_all()
                    if rows:
                        break
                    await asyncio.sleep(0.01)
                assert len(rows) == 1
                assert rows[0].status_code == 499
                assert rows[0].client_aborted is True
                assert rows[0].completed is False
                assert rows[0].status == "client-aborted"

    async def test_sequential_requests_reuse_the_real_upstream_connection(
        self, tmp_path: Path
    ) -> None:
        """The process-wide provider client keeps its upstream socket alive."""
        upstream_peers: list[tuple[str, int]] = []
        upstream = FastAPI()

        @upstream.post("/v1/messages")
        async def messages(request: Request) -> Response:
            if request.headers.get("x-api-key") != "provider-secret":
                raise HTTPException(status_code=401)
            if request.client is None:
                raise HTTPException(status_code=500, detail="missing peer")
            upstream_peers.append((request.client.host, request.client.port))
            await request.body()
            return Response(
                content=b"fixture-response",
                media_type="application/octet-stream",
            )

        async with _serve(upstream) as upstream_url:
            settings = GatewaySettings(
                control_token=SecretStr(_CONTROL_TOKEN),
                upstreams={
                    ProviderBinding.ANTHROPIC: UpstreamSettings(
                        base_url=upstream_url,
                        api_key=SecretStr("provider-secret"),
                        auth_style=UpstreamAuthStyle.X_API_KEY,
                    )
                },
                ledger_path=tmp_path / "reuse-gateway.jsonl",
                body_dir=tmp_path / "reuse-bodies",
                max_connections=2,
                max_keepalive_connections=1,
            )
            store = VirtualKeyStore(max_ttl_seconds=300)
            minted = store.mint(
                MintKeyRequest(
                    principal_kind="spawn",
                    principal_id="connection-reuse",
                    spawn_id="spawn-reuse",
                    repo_slug="acme/hydraflow",
                    repo_class="hydraflow",
                    provider_binding="anthropic",
                    capture_bodies=False,
                    ttl_seconds=60,
                )
            )
            gateway = create_app(settings, key_store=store)

            async with (
                _serve(gateway) as gateway_url,
                httpx.AsyncClient(timeout=5) as client,
            ):
                responses = [
                    await client.post(
                        f"{gateway_url}/v1/messages",
                        headers={"authorization": f"Bearer {minted.token}"},
                        content=b'{"model":"claude-sonnet-4-6"}',
                    )
                    for _ in range(2)
                ]

        assert [response.status_code for response in responses] == [200, 200]
        assert [response.content for response in responses] == [
            b"fixture-response",
            b"fixture-response",
        ]
        assert len(upstream_peers) == 2
        assert upstream_peers[0] == upstream_peers[1]

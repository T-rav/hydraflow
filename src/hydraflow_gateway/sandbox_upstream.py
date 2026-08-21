"""Deterministic Anthropic-compatible HTTP fake for sandbox conformance tests."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

_DEFAULT_API_KEY = "hydraflow-sandbox-provider-key"

_SSE_CHUNKS = (
    b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_sandbox","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[],"stop_reason":null,"usage":{"input_tokens":17,"cache_creation_input_tokens":3,"cache_read_input_tokens":5}}}\n\n',
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"checking tools"}}\n\n',
    b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    b'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_sandbox","name":"Read","input":{}}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"file_path\\":\\"README.md\\"}"}}\n\n',
    b'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":null},"usage":{"output_tokens":23}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)

_COMPLETION_SSE_CHUNKS = (
    b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_sandbox_complete","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[],"stop_reason":null,"usage":{"input_tokens":29}}}\n\n',
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"sandbox tool round trip complete"}}\n\n',
    b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":8}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)


class _ObservationState:
    def __init__(self) -> None:
        self.latest: dict[str, Any] = {}
        self.request_count = 0


def create_sandbox_app(*, api_key: str | None = None) -> FastAPI:
    """Create the fake upstream; never include its provider key in responses."""
    expected_key = api_key or os.environ.get(
        "SANDBOX_UPSTREAM_API_KEY", _DEFAULT_API_KEY
    )
    observations = _ObservationState()
    app = FastAPI(title="hydraflow-gateway-sandbox-upstream")
    app.state.observations = observations

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/messages", response_model=None)
    async def messages(request: Request) -> JSONResponse | StreamingResponse:
        presented = request.headers.get("x-api-key", "")
        if not secrets.compare_digest(presented, expected_key):
            raise HTTPException(status_code=401, detail="invalid provider credential")
        body = await request.body()
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        observations.request_count += 1
        tool_result_observed = _has_tool_result(payload.get("messages"))
        observations.latest = {
            "method": request.method,
            "path": request.url.path,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "model": payload.get("model"),
            "anthropic_beta": request.headers.get("anthropic-beta"),
            "anthropic_version": request.headers.get("anthropic-version"),
            "provider_auth_valid": True,
            "client_aborted": False,
            "completed": False,
            "request_count": observations.request_count,
            "tool_result_observed": tool_result_observed,
        }
        scenario = payload.get("sandbox_scenario")
        if scenario == "rate-limit":
            observations.latest["completed"] = True
            return JSONResponse(
                status_code=429,
                content={"type": "error", "error": {"type": "rate_limit_error"}},
                headers={"retry-after": "1"},
            )
        if scenario == "overloaded":
            observations.latest["completed"] = True
            return JSONResponse(
                status_code=529,
                content={
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "sandbox busy"},
                },
            )
        delay_ms = payload.get("sandbox_chunk_delay_ms", 0)
        delay_seconds = (
            float(delay_ms) / 1000
            if isinstance(delay_ms, int | float) and not isinstance(delay_ms, bool)
            else 0.0
        )

        async def stream() -> AsyncIterator[bytes]:
            completed = False
            try:
                chunks = _COMPLETION_SSE_CHUNKS if tool_result_observed else _SSE_CHUNKS
                for chunk in chunks:
                    yield chunk
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
                completed = True
            finally:
                observations.latest["completed"] = completed
                observations.latest["client_aborted"] = not completed

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    @app.get("/observations/latest")
    async def latest_observation() -> dict[str, Any]:
        return dict(observations.latest)

    return app


def _has_tool_result(raw_messages: object) -> bool:
    if not isinstance(raw_messages, list):
        return False
    for message in raw_messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            return True
    return False


def main() -> None:
    """Run the deterministic upstream as a sandbox-only container process."""
    host = os.environ.get(
        "SANDBOX_UPSTREAM_HOST", os.environ.get("GATEWAY_HOST", "127.0.0.1")
    )
    port = int(os.environ.get("SANDBOX_UPSTREAM_PORT", "8090"))
    uvicorn.run(
        "hydraflow_gateway.sandbox_upstream:create_sandbox_app",
        factory=True,
        host=host,
        port=port,
        workers=1,
    )


if __name__ == "__main__":
    main()

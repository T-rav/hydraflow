"""Golden direct-versus-gateway replay checks for provider response fixtures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

import hydraflow_gateway.app as gateway_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayLedger
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gateway"
_MANIFEST = json.loads(
    (_FIXTURE_DIR / "conformance_manifest.json").read_text(encoding="utf-8")
)
_CLI_SANDBOX_EVIDENCE = json.loads(
    (_FIXTURE_DIR / "claude_cli_sandbox_evidence.json").read_text(encoding="utf-8")
)
_CASES: tuple[dict[str, Any], ...] = tuple(_MANIFEST["cases"])
_HOP_BY_HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}
_CONTROL_TOKEN = "test-control-token-0123456789abcdef"


class _FixtureStream(httpx.AsyncByteStream):
    """Yield golden bytes at boundaries unrelated to SSE event boundaries."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def __aiter__(self) -> AsyncIterator[bytes]:
        offset = 0
        sizes = (1, 2, 7, 31, 257, 1024, 13, 509)
        index = 0
        while offset < len(self._payload):
            size = sizes[index % len(sizes)]
            yield self._payload[offset : offset + size]
            offset += size
            index += 1


def _settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://provider.test",
                api_key=SecretStr("provider-secret"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _mint(store: VirtualKeyStore) -> str:
    return store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="fixture-conformance",
            spawn_id="spawn-conformance",
            session_id="session-conformance",
            repo_slug="acme/hydraflow",
            repo_class="hydraflow",
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=60,
        )
    ).token


def _headers_without_hop_fields(
    raw_headers: Iterable[tuple[bytes, bytes]],
) -> tuple[tuple[bytes, bytes], ...]:
    headers = tuple((name.lower(), value) for name, value in raw_headers)
    blocked = set(_HOP_BY_HOP_HEADERS)
    for name, value in headers:
        if name == b"connection":
            blocked.update(
                item.strip().lower() for item in value.split(b",") if item.strip()
            )
    return tuple((name, value) for name, value in headers if name not in blocked)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: str(case["name"]))
async def test_gateway_conformance_matches_direct_fixture_bytes_and_headers(
    tmp_path: Path,
    case: dict[str, Any],
) -> None:
    """A single gateway attempt must be indistinguishable from direct replay."""
    fixture = (_FIXTURE_DIR / str(case["fixture"])).read_bytes()
    calls: list[httpx.Request] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        await request.aread()
        calls.append(request)
        headers: list[tuple[str, str]] = [
            ("content-type", str(case["content_type"])),
            ("x-request-id", f"req-{case['name']}"),
            ("anthropic-ratelimit-requests-remaining", "17"),
            ("set-cookie", "fixture-a=1"),
            ("set-cookie", "fixture-b=2"),
            ("connection", "x-fixture-hop"),
            ("x-fixture-hop", "must-be-removed"),
        ]
        if case["retry_after"] is not None:
            headers.append(("retry-after", str(case["retry_after"])))
        return httpx.Response(
            int(case["status_code"]),
            headers=headers,
            stream=_FixtureStream(fixture),
        )

    settings = _settings(tmp_path)
    store = VirtualKeyStore(max_ttl_seconds=300)
    token = _mint(store)
    ledger = GatewayLedger(settings.ledger_path)
    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app = gateway_app.create_app(
        settings,
        key_store=store,
        client=provider_client,
        ledger=ledger,
    )
    gateway_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    )
    request_body = b'{"model":"claude-sonnet-4-6","stream":true}'

    try:
        direct = await provider_client.post(
            "https://provider.test/v1/messages?beta=fixture",
            headers={
                "x-api-key": "provider-secret",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            content=request_body,
        )
        through_gateway = await gateway_client.post(
            "/v1/messages?beta=fixture",
            headers={
                "authorization": f"Bearer {token}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            content=request_body,
        )
    finally:
        await gateway_client.aclose()
        await provider_client.aclose()

    expected_digest = str(case["expected_sha256"])
    direct_digest = hashlib.sha256(direct.content).hexdigest()
    gateway_digest = hashlib.sha256(through_gateway.content).hexdigest()
    assert direct.status_code == int(case["status_code"])
    assert through_gateway.status_code == direct.status_code
    assert direct.content == fixture
    assert through_gateway.content == direct.content
    assert direct_digest == expected_digest == str(case["direct_sha256"])
    assert gateway_digest == expected_digest == str(case["gateway_sha256"])
    assert _headers_without_hop_fields(through_gateway.headers.raw) == (
        _headers_without_hop_fields(direct.headers.raw)
    )
    assert "connection" not in through_gateway.headers
    assert "x-fixture-hop" not in through_gateway.headers
    assert len(calls) == 2
    assert all(request.headers["x-api-key"] == "provider-secret" for request in calls)
    assert all("authorization" not in request.headers for request in calls)
    assert all(request.content == request_body for request in calls)
    rows = ledger.read_all()
    assert len(rows) == 1
    assert rows[0].status_code == int(case["status_code"])


def test_gateway_conformance_manifest_pins_long_and_interleaved_shapes() -> None:
    """The named cases remain meaningful protocol fixtures, not tiny stubs."""
    long_stream = (_FIXTURE_DIR / "long_stream.sse").read_bytes()
    interleaved = (_FIXTURE_DIR / "thinking_tool_use.sse").read_bytes()

    assert _MANIFEST["live_provider_session"] is False
    assert len(long_stream) > 4096
    first_thinking = interleaved.index(b'"type":"thinking"')
    tool_use = interleaved.index(b'"type":"tool_use"')
    second_thinking = interleaved.index(b'"type":"thinking"', first_thinking + 1)
    assert first_thinking < tool_use < second_thinking


def test_actual_claude_cli_sandbox_evidence_is_honest_and_sanitized() -> None:
    """Checked-in CLI evidence must not overstate its external-provider scope."""
    evidence = _CLI_SANDBOX_EVIDENCE
    gateway = evidence["gateway"]
    session = evidence["session"]
    credential_boundary = evidence["credential_boundary"]

    assert evidence["actual_claude_cli"] is True
    assert evidence["live_provider_session"] is False
    assert session["cli_exit_code"] == 0
    assert session["terminal_reason"] == "completed"
    assert session["tool_result_observed_upstream"] is True
    assert gateway["ledger_row_count"] == gateway["upstream_exchange_count"]
    assert gateway["status_codes"] == [200, 200, 200]
    assert gateway["body_capture_count"] == 0
    assert (
        credential_boundary["real_provider_credentials_present_in_cli_environment"]
        is False
    )

    forbidden_keys = {
        "control_token",
        "key_id",
        "prompt",
        "provider_api_key",
        "raw_headers",
        "request_body",
        "request_id",
        "session_id",
        "virtual_key",
    }

    def collect_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                child_key
                for child in value.values()
                for child_key in collect_keys(child)
            }
        if isinstance(value, list):
            return {child_key for child in value for child_key in collect_keys(child)}
        return set()

    assert collect_keys(evidence).isdisjoint(forbidden_keys)


async def test_gateway_http_client_timeout_policy_preserves_unbounded_sse_reads(
    tmp_path: Path,
) -> None:
    """Connect/write/pool are bounded while a valid long stream has no read cap."""
    settings = _settings(tmp_path).model_copy(
        update={
            "connect_timeout_seconds": 1.25,
            "write_timeout_seconds": 45.5,
            "pool_timeout_seconds": 2.75,
        }
    )

    client = gateway_app._build_http_client(settings)
    try:
        assert client.timeout.connect == 1.25
        assert client.timeout.read is None
        assert client.timeout.write == 45.5
        assert client.timeout.pool == 2.75
        assert client.follow_redirects is False
    finally:
        await client.aclose()

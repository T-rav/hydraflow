from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import scripts.gateway_probe as probe_module
from pydantic import SecretStr, ValidationError
from scripts.gateway_probe import run_probe

from hydraflow_gateway.app import create_app
from hydraflow_gateway.ledger import GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)


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


def _record_capture(
    ledger_path: Path,
    body_dir: Path,
    *,
    capture_id: str,
    key_id: str,
    provider_binding: str,
    response_body: bytes,
) -> None:
    body_dir.mkdir(parents=True, exist_ok=True)
    (body_dir / f"{capture_id}.request.body").write_bytes(b"sensitive request")
    (body_dir / f"{capture_id}.response.body").write_bytes(response_body)
    row = _capture_row(
        capture_id=capture_id,
        key_id=key_id,
        provider_binding=provider_binding,
    )
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _capture_row(
    *,
    capture_id: str = "capture-test",
    key_id: str = "key-test",
    provider_binding: str = "zai-harness",
) -> dict[str, Any]:
    return {
        "request_id": capture_id,
        "source": "gateway",
        "key_id": key_id,
        "body_capture_policy": "full",
        "status_code": 200,
        "status": "completed",
        "upstream_provider": provider_binding,
        "model_requested": (
            "glm-5.2" if provider_binding == "zai-harness" else "claude-test"
        ),
        "completed": True,
        "client_aborted": False,
        "body_capture_id": capture_id,
        "body_capture_complete": True,
    }


def _agent_receipt() -> dict[str, Any]:
    return {
        "receipt_kind": "queued_agent_canary",
        "actual_agent_cli": True,
        "agent_runtime": "test-cli",
        "runtime_version": "0.test",
        "role": "planner",
        "issue_number": 1,
        "model_requested": "test-model",
        "provider_binding": "zai-harness",
        "live_provider_session": True,
        "tool_call_count": 2,
        "tool_result_count": 2,
        "validated_output_observed": True,
        "issue_transition": "test-ready",
        "gateway_completed_200_count": 2,
        "gateway_marker_termination_499_count": 1,
        "gateway_body_capture_policy": "metadata-only",
    }


def _probe_evidence(
    *,
    agent_session: dict[str, Any] | None = None,
) -> probe_module.ProbeEvidence:
    digest = {"byte_count": 1, "sha256": "0" * 64}
    turn = {
        "status_code": 200,
        "downstream": digest,
        "captured_upstream": digest,
        "byte_identical": True,
    }
    return probe_module.ProbeEvidence.model_validate(
        {
            "recorded_at": datetime.now(UTC),
            "live_provider_session": True,
            "provider_binding": "zai-harness",
            "model_requested": "test-model",
            "first_turn": turn,
            "second_turn": turn,
            "tool_use_observed": True,
            "completion_observed": True,
            "raw_capture_cleanup_verified": True,
            "agent_session": agent_session,
        }
    )


def _collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child_key for child in value.values() for child_key in _collect_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _collect_keys(child)}
    return set()


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
async def test_probe_proves_same_request_bytes_and_cleans_raw_captures(
    tmp_path: Path,
) -> None:
    upstream_requests: list[httpx.Request] = []
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"
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

    async def upstream(request: httpx.Request) -> httpx.Response:
        await request.aread()
        upstream_requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(next(turns)),
        )

    control_token = "test-control-token-0123456789abcdef"
    settings = GatewaySettings(
        control_token=SecretStr(control_token),
        upstreams={
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://provider.test",
                api_key=SecretStr("provider-secret"),
                auth_style=UpstreamAuthStyle.BEARER,
            )
        },
        ledger_path=ledger_path,
        body_dir=body_dir,
        body_capture_repo_slugs=frozenset({"t-rav/hydraflow"}),
    )
    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app = create_app(settings, client=provider_client)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://gateway",
        ) as client:
            evidence = await run_probe(
                gateway_base_url="http://gateway",
                control_token=control_token,
                model="glm-5.2",
                provider_binding="zai-harness",
                ledger_path=ledger_path,
                body_dir=body_dir,
                live_provider_session=True,
                client=client,
            )
    finally:
        await provider_client.aclose()

    rows = GatewayLedger(ledger_path).read_all()
    assert len(rows) == 2
    assert all(row.body_capture_policy == "full" for row in rows)
    assert all(row.body_capture_complete is True for row in rows)
    assert all(row.upstream_provider == "zai-harness" for row in rows)
    assert all(row.status_code == 200 for row in rows)
    assert all(
        request.headers["authorization"] == "Bearer provider-secret"
        for request in upstream_requests
    )
    assert all("x-api-key" not in request.headers for request in upstream_requests)

    assert evidence.tool_use_observed is True
    assert evidence.completion_observed is True
    assert evidence.live_provider_session is True
    assert evidence.provider_binding == "zai-harness"
    assert evidence.first_turn.downstream.byte_count == len(first)
    assert evidence.first_turn.captured_upstream.byte_count == len(first)
    assert evidence.first_turn.byte_identical is True
    assert evidence.second_turn.downstream.byte_count == len(second)
    assert evidence.second_turn.captured_upstream.byte_count == len(second)
    assert evidence.second_turn.byte_identical is True
    assert evidence.raw_capture_cleanup_verified is True
    assert list(body_dir.glob("*.body")) == []
    serialized = evidence.model_dump_json()
    assert control_token not in serialized
    assert "provider-secret" not in serialized
    assert "gateway_probe_echo" not in serialized
    assert all(row.key_id not in serialized for row in rows)
    assert all(row.request_id not in serialized for row in rows)
    assert len(upstream_requests) == 2

    artifact = evidence.model_dump(mode="json")
    assert set(artifact) == {
        "schema_version",
        "evidence_kind",
        "recorded_at",
        "live_provider_session",
        "provider_binding",
        "model_requested",
        "comparison_method",
        "first_turn",
        "second_turn",
        "tool_use_observed",
        "completion_observed",
        "raw_capture_cleanup_verified",
        "agent_session",
        "sanitization",
    }
    assert artifact["schema_version"] == 1
    assert artifact["evidence_kind"] == "gateway_same_request_probe"
    assert artifact["comparison_method"] == (
        "gateway_captured_upstream_vs_downstream_raw_bytes"
    )
    assert _collect_keys(artifact).isdisjoint(
        {
            "body_dir",
            "capture_id",
            "control_token",
            "gateway_base_url",
            "key_id",
            "ledger_path",
            "prompt",
            "provider_api_key",
            "raw_headers",
            "raw_response",
            "request_body",
            "request_id",
            "session_id",
            "virtual_key",
        }
    )


def test_agent_session_receipt_schema_accepts_only_sanitized_metrics(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "agent-session.json"
    receipt = _agent_receipt()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    parsed = probe_module._load_agent_session_receipt(receipt_path)

    assert parsed.model_dump(mode="json") == receipt
    receipt["prompt"] = "must never enter the evidence schema"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(RuntimeError, match="agent-session receipt is invalid"):
        probe_module._load_agent_session_receipt(receipt_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider_binding", "anthropic", "provider does not match"),
        ("model_requested", "other-model", "model does not match"),
        ("live_provider_session", False, "live-provider claim does not match"),
    ],
)
def test_probe_evidence_rejects_contradictory_agent_receipt(
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = _agent_receipt()
    receipt[field] = value

    with pytest.raises(ValidationError, match=message):
        _probe_evidence(agent_session=receipt)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", "other", "wrong source"),
        ("body_capture_policy", "metadata-only", "full body capture"),
        ("body_capture_complete", False, "did not complete"),
        ("upstream_provider", "anthropic", "wrong upstream provider"),
        ("model_requested", "other-model", "wrong requested model"),
        ("status_code", 201, "status codes differ"),
        ("status", "upstream-error", "wrong terminal status"),
        ("completed", False, "did not record a completed request"),
        ("body_capture_id", "../unsafe", "invalid body capture id"),
    ],
)
def test_probe_capture_row_contract_fails_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    row = _capture_row()
    row[field] = value

    with pytest.raises(RuntimeError, match=message):
        probe_module._capture_id_from_row(
            row,
            provider_binding="zai-harness",
            model="glm-5.2",
            status_code=200,
        )


def test_probe_ledger_reader_tolerates_partial_tail_but_rejects_bad_rows(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    matching = _capture_row()
    unrelated = _capture_row(key_id="other-key")
    ledger_path.write_text(
        "\n" + json.dumps(unrelated) + "\n" + json.dumps(matching) + "\n{",
        encoding="utf-8",
    )

    assert probe_module._matching_probe_rows(ledger_path, "key-test") == [matching]

    ledger_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="non-object"):
        probe_module._matching_probe_rows(ledger_path, "key-test")


def test_probe_cli_accepts_zai_capture_and_receipt_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = [
        "gateway_probe.py",
        "--provider-binding",
        "zai-harness",
        "--model",
        "glm-5.2",
        "--ledger-path",
        str(tmp_path / "gateway.jsonl"),
        "--body-dir",
        str(tmp_path / "bodies"),
        "--agent-session-receipt",
        str(tmp_path / "receipt.json"),
        "--live-provider-session",
        "--artifact",
        str(tmp_path / "evidence.json"),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    args = probe_module._parse_args()

    assert args.provider_binding == "zai-harness"
    assert args.model == "glm-5.2"
    assert args.ledger_path == tmp_path / "gateway.jsonl"
    assert args.body_dir == tmp_path / "bodies"
    assert args.agent_session_receipt == tmp_path / "receipt.json"
    assert args.live_provider_session is True


def test_probe_main_writes_only_the_sanitized_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "nested" / "evidence.json"
    captured: dict[str, object] = {}

    async def fake_run_probe(**kwargs: object) -> probe_module.ProbeEvidence:
        captured.update(kwargs)
        return _probe_evidence()

    monkeypatch.setattr(probe_module, "run_probe", fake_run_probe)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gateway_probe.py",
            "--provider-binding",
            "zai-harness",
            "--model",
            "test-model",
            "--live-provider-session",
            "--artifact",
            str(artifact_path),
        ],
    )

    assert probe_module.main() == 0

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["evidence_kind"] == "gateway_same_request_probe"
    assert artifact["provider_binding"] == "zai-harness"
    assert artifact["live_provider_session"] is True
    assert _collect_keys(artifact).isdisjoint(
        {"control_token", "key_id", "request_id", "session_id", "raw_response"}
    )
    assert captured["control_token"] == "control-secret"
    assert captured["provider_binding"] == "zai-harness"


@pytest.mark.asyncio
async def test_probe_rejects_byte_mismatch_after_cleaning_raw_captures(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"
    downstream = _sse({"type": "message_stop"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/control/v1/keys":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-mismatch",
                    "token": "virtual-secret",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"key_id": "key-mismatch", "revoked": True})
        _record_capture(
            ledger_path,
            body_dir,
            capture_id="capture-mismatch",
            key_id="key-mismatch",
            provider_binding="zai-harness",
            response_body=b"different upstream bytes",
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(downstream),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="captured upstream bytes differ"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="glm-5.2",
                provider_binding="zai-harness",
                ledger_path=ledger_path,
                body_dir=body_dir,
                client=client,
            )

    assert list(body_dir.glob("*.body")) == []


@pytest.mark.asyncio
async def test_probe_fails_closed_when_key_mint_fails(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "no"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="key mint failed with HTTP 401"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="wrong",
                model="claude-test",
                ledger_path=tmp_path / "gateway.jsonl",
                body_dir=tmp_path / "bodies",
                client=client,
            )


@pytest.mark.asyncio
async def test_probe_cleans_raw_capture_when_gateway_request_fails(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/control/v1/keys":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-upstream-failure",
                    "token": "virtual-secret",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            )
        if request.method == "DELETE":
            return httpx.Response(
                200,
                json={"key_id": "key-upstream-failure", "revoked": True},
            )
        _record_capture(
            ledger_path,
            body_dir,
            capture_id="capture-upstream-failure",
            key_id="key-upstream-failure",
            provider_binding="anthropic",
            response_body=b"sensitive upstream error",
        )
        return httpx.Response(500, stream=_AsyncBytes(b"sensitive upstream error"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="request failed with HTTP 500"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="claude-test",
                ledger_path=ledger_path,
                body_dir=body_dir,
                client=client,
            )

    assert requests[-1].method == "DELETE"
    assert list(body_dir.glob("*.body")) == []


@pytest.mark.asyncio
async def test_probe_revokes_key_when_agentic_turn_fails(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"

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
        response_body = _sse({"type": "message_stop"})
        _record_capture(
            ledger_path,
            body_dir,
            capture_id="capture-failed-probe",
            key_id="key-failed-probe",
            provider_binding="anthropic",
            response_body=response_body,
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(response_body),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="did not observe the forced tool use"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="claude-test",
                ledger_path=ledger_path,
                body_dir=body_dir,
                client=client,
            )

    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/control/v1/keys/key-failed-probe"
    assert list(body_dir.glob("*.body")) == []


@pytest.mark.asyncio
async def test_probe_fails_when_key_revocation_is_not_acknowledged(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"
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
    turns = iter((("capture-first", first), ("capture-second", second)))

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
        capture_id, response_body = next(turns)
        _record_capture(
            ledger_path,
            body_dir,
            capture_id=capture_id,
            key_id="key-probe",
            provider_binding="anthropic",
            response_body=response_body,
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncBytes(response_body),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="key revocation failed with HTTP 503"):
            await run_probe(
                gateway_base_url="http://gateway",
                control_token="control-secret",
                model="claude-test",
                ledger_path=ledger_path,
                body_dir=body_dir,
                client=client,
            )

    assert list(body_dir.glob("*.body")) == []

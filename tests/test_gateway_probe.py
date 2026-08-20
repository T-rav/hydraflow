from __future__ import annotations

import json
import sys
from collections.abc import Callable
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
    model_served: object = "glm-5.2",
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
        "model_served": model_served,
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
        "gateway_count_scope": "shared_gateway_observation_window",
        "gateway_session_total_completed_200_count": 2,
        "gateway_session_total_marker_termination_499_count": 1,
        "gateway_body_capture_policy": "metadata-only",
    }


def _probe_evidence(
    *,
    agent_session: dict[str, Any] | None = None,
) -> probe_module.ProbeEvidence:
    digest = {"byte_count": 1, "sha256": "0" * 64}
    turn = {
        "status_code": 200,
        "model_served": "test-model-served",
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
            "key_revocation_verified": True,
            "agent_session": agent_session,
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("byte_count", 2), ("sha256", "1" * 64)],
)
def test_turn_evidence_rejects_inconsistent_equality_claim(
    field: str,
    value: object,
) -> None:
    payload = _probe_evidence().first_turn.model_dump(mode="json")
    payload["captured_upstream"][field] = value

    with pytest.raises(ValidationError, match="byte evidence must match exactly"):
        probe_module.TurnEvidence.model_validate(payload)


@pytest.mark.parametrize("model", ["", " \t"])
def test_probe_evidence_rejects_blank_requested_model(model: str) -> None:
    payload = _probe_evidence().model_dump(mode="json")
    payload["model_requested"] = model

    with pytest.raises(ValidationError, match="model"):
        probe_module.ProbeEvidence.model_validate(payload)


@pytest.mark.parametrize("model", ["", " \t"])
def test_turn_evidence_rejects_blank_served_model(model: str) -> None:
    payload = _probe_evidence().first_turn.model_dump(mode="json")
    payload["model_served"] = model

    with pytest.raises(ValidationError, match="model"):
        probe_module.TurnEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("turn", "status_code"),
    [("first_turn", 199), ("second_turn", 300)],
)
def test_probe_evidence_rejects_non_2xx_completed_turns(
    turn: str,
    status_code: int,
) -> None:
    payload = _probe_evidence().model_dump(mode="json")
    payload[turn]["status_code"] = status_code

    with pytest.raises(ValidationError, match="2xx status codes"):
        probe_module.ProbeEvidence.model_validate(payload)


def _collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child_key for child in value.values() for child_key in _collect_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _collect_keys(child)}
    return set()


async def _run_probe_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    ledger_path: Path,
    body_dir: Path,
    model: str = "claude-test",
    provider_binding: probe_module.ProviderBinding = "anthropic",
) -> probe_module.ProbeEvidence:
    """Run the common mock-transport probe setup used by failure tests."""

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await run_probe(
            gateway_base_url="http://gateway",
            control_token="control-secret",
            model=model,
            provider_binding=provider_binding,
            ledger_path=ledger_path,
            body_dir=body_dir,
            client=client,
        )


def _probe_control_response(
    request: httpx.Request,
    *,
    key_id: str,
    revoke_status: int = 200,
) -> httpx.Response | None:
    """Return the common successful mint/revoke response for mock probes."""

    if request.url.path == "/control/v1/keys":
        return httpx.Response(
            200,
            json={
                "key_id": key_id,
                "token": "virtual-secret",
                "expires_at": "2026-08-19T12:00:00Z",
            },
        )
    if request.method != "DELETE":
        return None
    if revoke_status >= 400:
        return httpx.Response(revoke_status)
    return httpx.Response(200, json={"key_id": key_id, "revoked": True})


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


def test_sse_bookkeeping_ignores_control_and_malformed_payloads() -> None:
    raw = (
        b"event: ping\r\n\r\n"
        b"data: [DONE]\r\n\r\n"
        b"data: {not-json}\n\n"
        b"data: []\n\n"
        b'data: {"type":\n'
        b'data: "message_stop"}\n\n'
    )

    assert probe_module._sse_payloads(raw) == [{"type": "message_stop"}]


@pytest.mark.parametrize("fragment", ["{", "[]"])
def test_tool_use_parser_rejects_malformed_or_non_object_input(fragment: str) -> None:
    raw = _sse(
        {
            "content_block": {
                "type": "tool_use",
                "id": "toolu_probe",
                "name": "gateway_probe_echo",
                "input": "not-an-object",
            }
        },
        {"delta": {"type": "input_json_delta", "partial_json": fragment}},
    )

    assert probe_module._tool_use_from_stream(raw) is None


def test_tool_use_parser_ignores_non_string_input_delta() -> None:
    raw = _sse(
        {
            "content_block": {
                "type": "tool_use",
                "id": "toolu_probe",
                "name": "gateway_probe_echo",
                "input": "not-an-object",
            }
        },
        {"delta": {"type": "input_json_delta", "partial_json": 1}},
    )

    assert probe_module._tool_use_from_stream(raw) == {
        "type": "tool_use",
        "id": "toolu_probe",
        "name": "gateway_probe_echo",
        "input": {},
    }


@pytest.mark.asyncio
async def test_probe_proves_same_request_bytes_and_cleans_raw_captures(
    tmp_path: Path,
) -> None:
    upstream_requests: list[httpx.Request] = []
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"
    first = _sse(
        {
            "type": "message_start",
            "message": {"model": "glm-5.3", "usage": {}},
        },
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
            "type": "message_start",
            "message": {"model": "glm-5.3", "usage": {}},
        },
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
    assert evidence.first_turn.model_served == "glm-5.3"
    assert evidence.first_turn.downstream.byte_count == len(first)
    assert evidence.first_turn.captured_upstream.byte_count == len(first)
    assert evidence.first_turn.byte_identical is True
    assert evidence.second_turn.downstream.byte_count == len(second)
    assert evidence.second_turn.captured_upstream.byte_count == len(second)
    assert evidence.second_turn.byte_identical is True
    assert evidence.second_turn.model_served == "glm-5.3"
    assert evidence.raw_capture_cleanup_verified is True
    assert evidence.key_revocation_verified is True
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
        "key_revocation_verified",
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


def test_agent_session_receipt_rejects_ambiguous_issue_scoped_gateway_counts(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "agent-session.json"
    receipt = _agent_receipt()
    receipt["gateway_completed_200_count"] = receipt.pop(
        "gateway_session_total_completed_200_count"
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RuntimeError, match="agent-session receipt is invalid"):
        probe_module._load_agent_session_receipt(receipt_path)


def test_live_provider_probe_evidence_fixture_is_strict_and_sanitized() -> None:
    artifact_path = (
        Path(__file__).parent
        / "fixtures"
        / "gateway"
        / "live_provider_probe_evidence.json"
    )

    evidence = probe_module.ProbeEvidence.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )

    assert evidence.live_provider_session is True
    assert evidence.provider_binding == "zai-harness"
    assert evidence.model_requested == "glm-5.2"
    assert evidence.first_turn.model_served == "glm-5.3"
    assert evidence.first_turn.byte_identical is True
    assert evidence.second_turn.model_served == "glm-5.3"
    assert evidence.second_turn.byte_identical is True
    assert evidence.raw_capture_cleanup_verified is True
    assert evidence.key_revocation_verified is True
    assert evidence.agent_session is not None
    assert evidence.agent_session.issue_number == 11464
    assert evidence.agent_session.gateway_count_scope == (
        "shared_gateway_observation_window"
    )
    assert evidence.agent_session.gateway_session_total_completed_200_count == 50
    assert (
        evidence.agent_session.gateway_session_total_marker_termination_499_count == 2
    )


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
        ("model_served", None, "no served model"),
        ("model_served", " ", "no served model"),
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
        probe_module._capture_details_from_row(
            row,
            provider_binding="zai-harness",
            model="glm-5.2",
            status_code=200,
        )


def test_raw_capture_cleanup_reports_unlink_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = (tmp_path / "request.body", tmp_path / "response.body")
    for path in paths:
        path.write_bytes(b"sensitive")

    def fail_unlink(path: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError

    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(RuntimeError, match="could not delete"):
            probe_module._remove_capture_paths(paths)

    for path in paths:
        path.unlink()


@pytest.mark.asyncio
async def test_turn_proof_rejects_missing_raw_capture(tmp_path: Path) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    ledger_path.write_text(json.dumps(_capture_row()) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="raw body capture is missing"):
        await probe_module._prove_turn_bytes(
            ledger_path=ledger_path,
            body_dir=tmp_path / "bodies",
            key_id="key-test",
            provider_binding="zai-harness",
            model="glm-5.2",
            turn_index=0,
            status_code=200,
            downstream_raw=b"downstream",
        )


@pytest.mark.asyncio
async def test_turn_proof_reports_unreadable_upstream_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    body_dir = tmp_path / "bodies"
    _record_capture(
        ledger_path,
        body_dir,
        capture_id="capture-test",
        key_id="key-test",
        provider_binding="zai-harness",
        response_body=b"upstream",
    )

    def fail_read_bytes(path: Path) -> bytes:
        raise PermissionError

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    with pytest.raises(RuntimeError, match="could not read its upstream capture"):
        await probe_module._prove_turn_bytes(
            ledger_path=ledger_path,
            body_dir=body_dir,
            key_id="key-test",
            provider_binding="zai-harness",
            model="glm-5.2",
            turn_index=0,
            status_code=200,
            downstream_raw=b"downstream",
        )

    assert list(body_dir.glob("*.body")) == []


def test_terminal_capture_cleanup_skips_absent_id_and_rejects_invalid_id(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "gateway.jsonl"
    rows = [
        {"key_id": "key-test", "body_capture_id": None},
        {"key_id": "key-test", "body_capture_id": "../unsafe"},
    ]
    ledger_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid body capture id"):
        probe_module._cleanup_probe_captures(
            ledger_path,
            tmp_path / "bodies",
            "key-test",
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

    ledger_path.write_text("{\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid gateway ledger JSON"):
        probe_module._matching_probe_rows(ledger_path, "key-test")


def test_probe_ledger_reader_handles_missing_file_and_reports_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "missing.jsonl"
    assert probe_module._matching_probe_rows(ledger_path, "key-test") == []

    def fail_read_text(path: Path, *, encoding: str) -> str:
        raise PermissionError

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    with pytest.raises(RuntimeError, match="could not read the gateway ledger"):
        probe_module._matching_probe_rows(ledger_path, "key-test")


@pytest.mark.asyncio
async def test_probe_ledger_wait_times_out_without_a_matching_row(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="timed out waiting"):
        await probe_module._wait_for_probe_row(
            tmp_path / "missing.jsonl",
            "key-test",
            turn_index=0,
            timeout_seconds=0,
        )


@pytest.mark.asyncio
async def test_probe_ledger_wait_retries_until_row_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _capture_row()
    snapshots = iter(([], [expected]))
    monkeypatch.setattr(
        probe_module,
        "_matching_probe_rows",
        lambda ledger_path, key_id: next(snapshots),
    )

    row = await probe_module._wait_for_probe_row(
        Path("unused.jsonl"),
        "key-test",
        turn_index=0,
    )

    assert row == expected


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
        control_response = _probe_control_response(request, key_id="key-mismatch")
        if control_response is not None:
            return control_response
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

    with pytest.raises(RuntimeError, match="captured upstream bytes differ"):
        await _run_probe_with_handler(
            handler,
            ledger_path=ledger_path,
            body_dir=body_dir,
            model="glm-5.2",
            provider_binding="zai-harness",
        )

    assert list(body_dir.glob("*.body")) == []


@pytest.mark.asyncio
async def test_probe_fails_closed_when_key_mint_fails(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "no"})

    with pytest.raises(RuntimeError, match="key mint failed with HTTP 401"):
        await _run_probe_with_handler(
            handler,
            ledger_path=tmp_path / "gateway.jsonl",
            body_dir=tmp_path / "bodies",
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
        control_response = _probe_control_response(
            request,
            key_id="key-upstream-failure",
        )
        if control_response is not None:
            return control_response
        _record_capture(
            ledger_path,
            body_dir,
            capture_id="capture-upstream-failure",
            key_id="key-upstream-failure",
            provider_binding="anthropic",
            response_body=b"sensitive upstream error",
        )
        return httpx.Response(500, stream=_AsyncBytes(b"sensitive upstream error"))

    with pytest.raises(RuntimeError, match="request failed with HTTP 500"):
        await _run_probe_with_handler(
            handler,
            ledger_path=ledger_path,
            body_dir=body_dir,
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
        control_response = _probe_control_response(
            request,
            key_id="key-failed-probe",
        )
        if control_response is not None:
            return control_response
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

    with pytest.raises(RuntimeError, match="did not observe the forced tool use"):
        await _run_probe_with_handler(
            handler,
            ledger_path=ledger_path,
            body_dir=body_dir,
        )

    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/control/v1/keys/key-failed-probe"
    assert list(body_dir.glob("*.body")) == []


@pytest.mark.asyncio
async def test_probe_fails_when_key_revocation_is_not_acknowledged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    evidence_constructions: list[dict[str, object]] = []
    evidence_type = probe_module.ProbeEvidence

    def record_evidence_construction(**kwargs: object) -> probe_module.ProbeEvidence:
        evidence_constructions.append(kwargs)
        return evidence_type(**kwargs)

    monkeypatch.setattr(probe_module, "ProbeEvidence", record_evidence_construction)

    def handler(request: httpx.Request) -> httpx.Response:
        control_response = _probe_control_response(
            request,
            key_id="key-probe",
            revoke_status=503,
        )
        if control_response is not None:
            return control_response
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

    with pytest.raises(RuntimeError, match="key revocation failed with HTTP 503"):
        await _run_probe_with_handler(
            handler,
            ledger_path=ledger_path,
            body_dir=body_dir,
        )

    assert list(body_dir.glob("*.body")) == []
    assert evidence_constructions == []


@pytest.mark.parametrize(
    ("failure_kind", "message"),
    [
        ("network", "key revocation failed"),
        ("invalid-json", "returned invalid JSON"),
        ("not-revoked", "was not acknowledged"),
    ],
)
@pytest.mark.asyncio
async def test_probe_key_revocation_fails_closed_on_unverified_response(
    failure_kind: str,
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure_kind == "network":
            raise httpx.ConnectError("unavailable", request=request)
        if failure_kind == "invalid-json":
            return httpx.Response(200, content=b"{")
        return httpx.Response(200, json={"revoked": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match=message):
            await probe_module._revoke_probe_key(
                client,
                base="http://gateway",
                control_token="control-secret",
                key_id="key-probe",
            )

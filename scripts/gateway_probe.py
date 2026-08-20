"""Run a sanitized two-turn agentic confidence probe through the gateway.

Each turn is matched to its gateway ledger row so the raw bytes observed by the
client can be compared with the upstream bytes captured for that exact request.
Raw request/response captures are deleted before the probe returns. The JSON
artifact deliberately omits prompts, model output, paths, request/key IDs, and
all credentials; it retains only the comparison result and sanitized metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ProviderBinding = Literal["anthropic", "zai-harness"]
_PROVIDER_BINDINGS: tuple[ProviderBinding, ...] = ("anthropic", "zai-harness")
_CAPTURE_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
_COMPARISON_METHOD = "gateway_captured_upstream_vs_downstream_raw_bytes"


class ByteEvidence(BaseModel):
    """Sanitized length and digest for one side of a byte comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TurnEvidence(BaseModel):
    """Same-request byte equality proof for one streamed turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    downstream: ByteEvidence
    captured_upstream: ByteEvidence
    byte_identical: Literal[True]


class SanitizationEvidence(BaseModel):
    """Machine-checkable omissions required for a committable artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_prompt_omitted: Literal[True] = True
    raw_model_output_omitted: Literal[True] = True
    request_and_key_ids_omitted: Literal[True] = True
    session_ids_omitted: Literal[True] = True
    request_headers_and_bodies_omitted: Literal[True] = True
    paths_omitted: Literal[True] = True
    virtual_control_and_provider_credentials_omitted: Literal[True] = True


class AgentSessionEvidence(BaseModel):
    """Optional sanitized receipt from a real queued agent canary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_kind: Literal["queued_agent_canary"] = "queued_agent_canary"
    actual_agent_cli: Literal[True]
    agent_runtime: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    role: str = Field(min_length=1)
    issue_number: int = Field(gt=0)
    model_requested: str = Field(min_length=1)
    provider_binding: ProviderBinding
    live_provider_session: bool
    tool_call_count: int = Field(ge=0)
    tool_result_count: int = Field(ge=0)
    validated_output_observed: Literal[True]
    issue_transition: str = Field(min_length=1)
    gateway_count_scope: Literal["shared_gateway_observation_window"]
    gateway_session_total_completed_200_count: int = Field(ge=0)
    gateway_session_total_marker_termination_499_count: int = Field(ge=0)
    gateway_body_capture_policy: Literal["metadata-only", "full"]


class ProbeEvidence(BaseModel):
    """Versioned, sanitized artifact emitted by a successful probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evidence_kind: Literal["gateway_same_request_probe"] = "gateway_same_request_probe"
    recorded_at: datetime
    live_provider_session: bool
    provider_binding: ProviderBinding
    model_requested: str
    comparison_method: Literal["gateway_captured_upstream_vs_downstream_raw_bytes"] = (
        _COMPARISON_METHOD
    )
    first_turn: TurnEvidence
    second_turn: TurnEvidence
    tool_use_observed: Literal[True]
    completion_observed: Literal[True]
    raw_capture_cleanup_verified: Literal[True]
    agent_session: AgentSessionEvidence | None = None
    sanitization: SanitizationEvidence = SanitizationEvidence()

    @model_validator(mode="after")
    def require_consistent_agent_receipt(self) -> Self:
        """Prevent a combined artifact from carrying contradictory receipts."""

        receipt = self.agent_session
        if receipt is None:
            return self
        if receipt.provider_binding != self.provider_binding:
            raise ValueError("agent receipt provider does not match probe provider")
        if receipt.model_requested != self.model_requested:
            raise ValueError("agent receipt model does not match probe model")
        if receipt.live_provider_session != self.live_provider_session:
            raise ValueError("agent receipt live-provider claim does not match probe")
        return self


def _load_agent_session_receipt(path: Path) -> AgentSessionEvidence:
    """Load only the allow-listed, sanitized queued-agent receipt schema."""

    try:
        return AgentSessionEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError):
        raise RuntimeError("gateway probe agent-session receipt is invalid") from None


def _new_probe_client() -> httpx.AsyncClient:
    """Build a probe client that never delegates gateway secrets to env proxies."""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, read=None),
        trust_env=False,
    )


def _sse_payloads(raw: bytes) -> list[dict[str, Any]]:
    """Decode JSON ``data:`` fields for probe bookkeeping only.

    Gateway conformance tests compare the original bytes. This parser never
    participates in proxying and therefore cannot rewrite production traffic.
    """

    payloads: list[dict[str, Any]] = []
    normalized = raw.replace(b"\r\n", b"\n")
    for event in normalized.split(b"\n\n"):
        data = b"\n".join(
            line[5:].lstrip()
            for line in event.splitlines()
            if line.startswith(b"data:")
        )
        if not data or data == b"[DONE]":
            continue
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _tool_use_from_stream(raw: bytes) -> dict[str, Any] | None:
    tool_id = ""
    tool_name = ""
    input_fragments: list[str] = []
    initial_input: dict[str, Any] | None = None
    for payload in _sse_payloads(raw):
        block = payload.get("content_block")
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_id = str(block.get("id", ""))
            tool_name = str(block.get("name", ""))
            if isinstance(block.get("input"), dict):
                initial_input = block["input"]
        delta = payload.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "input_json_delta":
            fragment = delta.get("partial_json")
            if isinstance(fragment, str):
                input_fragments.append(fragment)
    if not tool_id or not tool_name:
        return None
    tool_input: dict[str, Any] = initial_input or {}
    if input_fragments:
        try:
            parsed = json.loads("".join(input_fragments))
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        tool_input = parsed
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": tool_name,
        "input": tool_input,
    }


async def _stream_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
) -> tuple[int, bytes]:
    chunks: list[bytes] = []
    async with client.stream("POST", url, headers=headers, json=body) as response:
        async for chunk in response.aiter_raw():
            chunks.append(chunk)
        raw = b"".join(chunks)
        if response.status_code >= 400:
            raise RuntimeError(
                f"gateway probe request failed with HTTP {response.status_code}"
            )
        return response.status_code, raw


def _byte_evidence(raw: bytes) -> ByteEvidence:
    return ByteEvidence(byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _matching_probe_rows(ledger_path: Path, key_id: str) -> list[dict[str, Any]]:
    """Read complete JSONL rows belonging to this probe's ephemeral key."""

    try:
        text = ledger_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        raise RuntimeError("gateway probe could not read the gateway ledger") from None

    rows: list[dict[str, Any]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1 and not text.endswith("\n"):
                continue
            raise RuntimeError(
                "gateway probe found invalid gateway ledger JSON"
            ) from None
        if not isinstance(value, dict):
            raise RuntimeError("gateway probe found a non-object gateway ledger row")
        if value.get("key_id") == key_id:
            rows.append(value)
    return rows


async def _wait_for_probe_row(
    ledger_path: Path,
    key_id: str,
    *,
    turn_index: int,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Wait briefly for the response finalizer to append this turn's row."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        rows = _matching_probe_rows(ledger_path, key_id)
        if len(rows) > turn_index:
            return rows[turn_index]
        if loop.time() >= deadline:
            raise RuntimeError("gateway probe timed out waiting for its ledger row")
        await asyncio.sleep(0.01)


def _capture_id_from_row(
    row: dict[str, Any],
    *,
    provider_binding: ProviderBinding,
    model: str,
    status_code: int,
) -> str:
    """Validate that a ledger row describes a complete captured probe turn."""

    if row.get("source") != "gateway":
        raise RuntimeError("gateway probe ledger row has the wrong source")
    if row.get("body_capture_policy") != "full":
        raise RuntimeError("gateway probe ledger row did not use full body capture")
    if row.get("body_capture_complete") is not True:
        raise RuntimeError("gateway probe body capture did not complete")
    if row.get("upstream_provider") != provider_binding:
        raise RuntimeError("gateway probe ledger row used the wrong upstream provider")
    if row.get("model_requested") != model:
        raise RuntimeError(
            "gateway probe ledger row recorded the wrong requested model"
        )
    if row.get("status_code") != status_code:
        raise RuntimeError("gateway probe ledger and downstream status codes differ")
    if row.get("status") != "completed":
        raise RuntimeError("gateway probe ledger row has the wrong terminal status")
    if row.get("completed") is not True or row.get("client_aborted") is not False:
        raise RuntimeError(
            "gateway probe ledger row did not record a completed request"
        )
    capture_id = row.get("body_capture_id")
    if (
        not isinstance(capture_id, str)
        or _CAPTURE_ID_PATTERN.fullmatch(capture_id) is None
    ):
        raise RuntimeError("gateway probe ledger row has an invalid body capture id")
    return capture_id


def _capture_paths(body_dir: Path, capture_id: str) -> tuple[Path, Path]:
    return (
        body_dir / f"{capture_id}.request.body",
        body_dir / f"{capture_id}.response.body",
    )


def _remove_capture_paths(paths: tuple[Path, Path]) -> None:
    """Remove raw request/response files and fail if either survives."""

    cleanup_failed = False
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            cleanup_failed = True
    if cleanup_failed or any(path.exists() for path in paths):
        raise RuntimeError("gateway probe could not delete its raw body captures")


async def _prove_turn_bytes(
    *,
    ledger_path: Path,
    body_dir: Path,
    key_id: str,
    provider_binding: ProviderBinding,
    model: str,
    turn_index: int,
    status_code: int,
    downstream_raw: bytes,
) -> TurnEvidence:
    """Compare one downstream stream with its exact captured upstream body."""

    row = await _wait_for_probe_row(ledger_path, key_id, turn_index=turn_index)
    capture_id = _capture_id_from_row(
        row,
        provider_binding=provider_binding,
        model=model,
        status_code=status_code,
    )
    paths = _capture_paths(body_dir, capture_id)
    request_path, response_path = paths
    try:
        if not request_path.is_file() or not response_path.is_file():
            raise RuntimeError("gateway probe raw body capture is missing")
        try:
            captured_upstream_raw = response_path.read_bytes()
        except OSError:
            raise RuntimeError(
                "gateway probe could not read its upstream capture"
            ) from None
        downstream = _byte_evidence(downstream_raw)
        captured_upstream = _byte_evidence(captured_upstream_raw)
        if captured_upstream_raw != downstream_raw:
            raise RuntimeError("gateway captured upstream bytes differ from downstream")
        return TurnEvidence(
            status_code=status_code,
            downstream=downstream,
            captured_upstream=captured_upstream,
            byte_identical=True,
        )
    finally:
        _remove_capture_paths(paths)


def _cleanup_probe_captures(
    ledger_path: Path,
    body_dir: Path,
    key_id: str,
) -> None:
    """Best-effort terminal-path cleanup scoped to this probe's key."""

    for row in _matching_probe_rows(ledger_path, key_id):
        capture_id = row.get("body_capture_id")
        if capture_id is None:
            continue
        if (
            not isinstance(capture_id, str)
            or _CAPTURE_ID_PATTERN.fullmatch(capture_id) is None
        ):
            raise RuntimeError(
                "gateway probe ledger row has an invalid body capture id"
            )
        _remove_capture_paths(_capture_paths(body_dir, capture_id))


async def run_probe(
    *,
    gateway_base_url: str,
    control_token: str,
    model: str,
    ledger_path: Path,
    body_dir: Path,
    provider_binding: ProviderBinding = "anthropic",
    repo_slug: str = "t-rav/hydraflow",
    live_provider_session: bool = False,
    agent_session: AgentSessionEvidence | None = None,
    client: httpx.AsyncClient | None = None,
) -> ProbeEvidence:
    """Run a forced tool-use session with same-request capture comparison."""

    if provider_binding not in _PROVIDER_BINDINGS:
        raise ValueError(f"unsupported gateway provider binding: {provider_binding}")

    owns_client = client is None
    probe_client = client if client is not None else _new_probe_client()
    minted_key_id: str | None = None
    base = gateway_base_url.rstrip("/")
    try:
        mint = await probe_client.post(
            f"{base}/control/v1/keys",
            headers={"authorization": f"Bearer {control_token}"},
            json={
                "principal_kind": "role",
                "principal_id": "gateway-confidence-probe",
                "spawn_id": f"probe-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                "repo_slug": repo_slug,
                "repo_class": "hydraflow",
                "provider_binding": provider_binding,
                "capture_bodies": True,
                "ttl_seconds": 300,
            },
        )
        if mint.status_code >= 400:
            raise RuntimeError(f"gateway key mint failed with HTTP {mint.status_code}")
        minted = mint.json()
        token = minted.get("token")
        key_id = minted.get("key_id")
        if isinstance(key_id, str) and key_id:
            minted_key_id = key_id
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(key_id, str)
            or not key_id
        ):
            raise RuntimeError("gateway key mint returned an invalid response")

        headers = {
            "authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        user_prompt = (
            "Call gateway_probe_echo exactly once with value 'tap-ok'. "
            "After the tool result, reply with probe-complete."
        )
        tool = {
            "name": "gateway_probe_echo",
            "description": "Returns the supplied probe value unchanged.",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        }
        first_status, first_raw = await _stream_post(
            probe_client,
            f"{base}/v1/messages",
            headers=headers,
            body={
                "model": model,
                "max_tokens": 256,
                "stream": True,
                "messages": [{"role": "user", "content": user_prompt}],
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": "gateway_probe_echo"},
            },
        )
        first_evidence = await _prove_turn_bytes(
            ledger_path=ledger_path,
            body_dir=body_dir,
            key_id=key_id,
            provider_binding=provider_binding,
            model=model,
            turn_index=0,
            status_code=first_status,
            downstream_raw=first_raw,
        )
        tool_use = _tool_use_from_stream(first_raw)
        if tool_use is None:
            raise RuntimeError("gateway probe did not observe the forced tool use")

        second_status, second_raw = await _stream_post(
            probe_client,
            f"{base}/v1/messages",
            headers=headers,
            body={
                "model": model,
                "max_tokens": 128,
                "stream": True,
                "messages": [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": [tool_use]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use["id"],
                                "content": "tap-ok",
                            }
                        ],
                    },
                ],
                "tools": [tool],
            },
        )
        second_evidence = await _prove_turn_bytes(
            ledger_path=ledger_path,
            body_dir=body_dir,
            key_id=key_id,
            provider_binding=provider_binding,
            model=model,
            turn_index=1,
            status_code=second_status,
            downstream_raw=second_raw,
        )
        completion_observed = any(
            payload.get("type") == "message_stop"
            for payload in _sse_payloads(second_raw)
        )
        if not completion_observed:
            raise RuntimeError("gateway probe second turn did not complete")

        return ProbeEvidence(
            recorded_at=datetime.now(UTC),
            live_provider_session=live_provider_session,
            provider_binding=provider_binding,
            model_requested=model,
            first_turn=first_evidence,
            second_turn=second_evidence,
            tool_use_observed=True,
            completion_observed=True,
            raw_capture_cleanup_verified=True,
            agent_session=agent_session,
        )
    finally:
        try:
            try:
                if minted_key_id is not None:
                    await _revoke_probe_key(
                        probe_client,
                        base=base,
                        control_token=control_token,
                        key_id=minted_key_id,
                    )
            finally:
                if minted_key_id is not None:
                    _cleanup_probe_captures(ledger_path, body_dir, minted_key_id)
        finally:
            if owns_client:
                await probe_client.aclose()


async def _revoke_probe_key(
    client: httpx.AsyncClient,
    *,
    base: str,
    control_token: str,
    key_id: str,
) -> None:
    """Revoke probe credentials and fail without exposing response content."""
    try:
        response = await client.delete(
            f"{base}/control/v1/keys/{key_id}",
            headers={"authorization": f"Bearer {control_token}"},
        )
    except httpx.HTTPError:
        raise RuntimeError("gateway probe key revocation failed") from None
    if response.status_code >= 400:
        raise RuntimeError(
            f"gateway probe key revocation failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise RuntimeError(
            "gateway probe key revocation returned invalid JSON"
        ) from None
    if payload.get("revoked") is not True:
        raise RuntimeError("gateway probe key revocation was not acknowledged")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gateway-base-url",
        default=os.environ.get("HYDRAFLOW_GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--model", default="claude-sonnet-4-5")
    parser.add_argument(
        "--provider-binding",
        choices=_PROVIDER_BINDINGS,
        default="anthropic",
        help="Gateway upstream bound to the ephemeral probe key",
    )
    parser.add_argument("--repo-slug", default="t-rav/hydraflow")
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=Path(
            os.environ.get("GATEWAY_LEDGER_PATH", ".hydraflow/gateway/requests.jsonl")
        ),
        help="The exact GATEWAY_LEDGER_PATH used by the running gateway",
    )
    parser.add_argument(
        "--body-dir",
        type=Path,
        default=Path(os.environ.get("GATEWAY_BODY_DIR", ".hydraflow/gateway/bodies")),
        help="The exact GATEWAY_BODY_DIR used by the running gateway",
    )
    parser.add_argument(
        "--live-provider-session",
        action="store_true",
        help="Mark the artifact live only when the gateway uses a real provider",
    )
    parser.add_argument(
        "--agent-session-receipt",
        type=Path,
        default=None,
        help="Optional sanitized JSON receipt from a queued real-agent canary",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Explicit path for the sanitized JSON evidence artifact",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    control_token = os.environ.get("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "")
    if not control_token:
        raise SystemExit("HYDRAFLOW_GATEWAY_CONTROL_TOKEN is required")
    agent_session = (
        _load_agent_session_receipt(args.agent_session_receipt)
        if args.agent_session_receipt is not None
        else None
    )
    evidence = asyncio.run(
        run_probe(
            gateway_base_url=args.gateway_base_url,
            control_token=control_token,
            model=args.model,
            provider_binding=args.provider_binding,
            repo_slug=args.repo_slug,
            ledger_path=args.ledger_path,
            body_dir=args.body_dir,
            live_provider_session=args.live_provider_session,
            agent_session=agent_session,
        )
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"gateway probe passed; sanitized evidence: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a sanitized two-turn agentic confidence probe through the gateway.

The probe deliberately records no prompt, model output, virtual key, or control
credential. Its JSON artifact contains only response status, byte counts,
SHA-256 digests, and whether the forced tool-use round trip completed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class StreamEvidence:
    status_code: int
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class ProbeEvidence:
    timestamp: str
    model: str
    key_id: str
    first_turn: StreamEvidence
    second_turn: StreamEvidence
    tool_use_observed: bool
    completion_observed: bool


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
) -> tuple[StreamEvidence, bytes]:
    chunks: list[bytes] = []
    async with client.stream("POST", url, headers=headers, json=body) as response:
        async for chunk in response.aiter_raw():
            chunks.append(chunk)
        raw = b"".join(chunks)
        if response.status_code >= 400:
            raise RuntimeError(
                f"gateway probe request failed with HTTP {response.status_code}"
            )
        return (
            StreamEvidence(
                status_code=response.status_code,
                byte_count=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            ),
            raw,
        )


async def run_probe(
    *,
    gateway_base_url: str,
    control_token: str,
    model: str,
    repo_slug: str = "t-rav/hydraflow",
    client: httpx.AsyncClient | None = None,
) -> ProbeEvidence:
    """Mint a key and complete a forced tool-use turn plus tool-result turn."""

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
                "provider_binding": "anthropic",
                "capture_bodies": False,
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
        first_evidence, first_raw = await _stream_post(
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
        tool_use = _tool_use_from_stream(first_raw)
        if tool_use is None:
            raise RuntimeError("gateway probe did not observe the forced tool use")

        second_evidence, second_raw = await _stream_post(
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
        completion_observed = any(
            payload.get("type") == "message_stop"
            for payload in _sse_payloads(second_raw)
        )
        if not completion_observed:
            raise RuntimeError("gateway probe second turn did not complete")

        return ProbeEvidence(
            timestamp=datetime.now(UTC).isoformat(),
            model=model,
            key_id=key_id,
            first_turn=first_evidence,
            second_turn=second_evidence,
            tool_use_observed=True,
            completion_observed=True,
        )
    finally:
        try:
            if minted_key_id is not None:
                await _revoke_probe_key(
                    probe_client,
                    base=base,
                    control_token=control_token,
                    key_id=minted_key_id,
                )
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
    parser.add_argument("--repo-slug", default="t-rav/hydraflow")
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
    evidence = asyncio.run(
        run_probe(
            gateway_base_url=args.gateway_base_url,
            control_token=control_token,
            model=args.model,
            repo_slug=args.repo_slug,
        )
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"gateway probe passed; sanitized evidence: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

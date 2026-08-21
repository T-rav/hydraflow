"""Configured ADR reviewer canary through the production gateway seam."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

from config import HydraFlowConfig
from execution import HostRunner
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports

pytestmark = pytest.mark.scenario_loops

_CONTROL_TOKEN = "adr-canary-control-token-0123456789abcdef"
_PROVIDER_KEY = "adr-canary-real-provider-key"
_COUNCIL_TRANSCRIPT = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: REJECT
architect_reasoning: The rollout needs a smaller failure domain.
pragmatist_verdict: REJECT
pragmatist_reasoning: The operational rollback is not yet specified.
editor_verdict: REJECT
editor_reasoning: The consequences omit recovery behavior.
approve_count: 0
reject_count: 3
final_decision: REJECT
summary: The council rejected the proposal pending rollback and recovery details.
duplicate_of: none
minority_note: none
"""


@asynccontextmanager
async def _serve(app: Any) -> AsyncIterator[str]:
    """Serve one ASGI app on an ephemeral localhost socket."""
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


@dataclass(frozen=True, slots=True)
class _ProviderExchange:
    headers: httpx.Headers
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ProviderStream(httpx.AsyncByteStream):
    body: bytes

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = len(self.body) // 2
        yield self.body[:midpoint]
        yield self.body[midpoint:]


@dataclass(slots=True)
class _FakeAnthropicOrigin:
    """The sole mocked network boundary: deterministic Anthropic SSE."""

    exchanges: list[_ProviderExchange] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(await request.aread())
        self.exchanges.append(
            _ProviderExchange(headers=httpx.Headers(request.headers), payload=payload)
        )
        events = (
            'event: message_start\ndata: {"type":"message_start","message":'
            '{"model":"claude-sonnet-4-6","usage":{"input_tokens":29}}}\n\n'
            "event: content_block_delta\ndata: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": _COUNCIL_TRANSCRIPT},
                },
                separators=(",", ":"),
            )
            + "\n\n"
            'event: message_delta\ndata: {"type":"message_delta","usage":'
            '{"output_tokens":41}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        ).encode()
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ProviderStream(events),
        )


def _write_claude_shim(bin_dir: Path) -> None:
    """Install a deterministic CLI boundary that consumes gateway SSE."""
    bin_dir.mkdir(parents=True)
    executable = bin_dir / "claude"
    executable.write_text(
        """#!/usr/bin/env python3
import http.client
import json
import os
import sys
from urllib.parse import urlsplit

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
model = args[args.index("--model") + 1]
base = urlsplit(os.environ["ANTHROPIC_BASE_URL"])
connection = http.client.HTTPConnection(base.hostname, base.port, timeout=5)
body = json.dumps({
    "model": model,
    "stream": True,
    "messages": [{"role": "user", "content": prompt}],
}).encode()
connection.request(
    "POST",
    f"{base.path.rstrip('/')}/v1/messages",
    body=body,
    headers={
        "Authorization": f"Bearer {os.environ['ANTHROPIC_AUTH_TOKEN']}",
        "Content-Type": "application/json",
        "Anthropic-Version": "2023-06-01",
        "X-Canary-Control-Present": str(bool(os.environ.get("HYDRAFLOW_GATEWAY_CONTROL_TOKEN"))).lower(),
        "X-Canary-Provider-Key-Present": str(bool(os.environ.get("ANTHROPIC_API_KEY"))).lower(),
    },
)
response = connection.getresponse()
raw = response.read()
if response.status != 200:
    sys.stderr.write(f"gateway returned {response.status}")
    raise SystemExit(1)
text = ""
for line in raw.splitlines():
    if not line.startswith(b"data: "):
        continue
    event = json.loads(line[6:])
    delta = event.get("delta")
    if isinstance(delta, dict) and delta.get("type") == "text_delta":
        text += str(delta.get("text", ""))
sys.stdout.write(text)
connection.close()
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _write_proposed_adr(repo_root: Path) -> None:
    adr_dir = repo_root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "9001-gateway-canary.md").write_text(
        """# ADR-9001: Gateway Canary

**Status:** Proposed

## Context

The maintenance fleet needs a bounded transport canary.

## Decision

Route the ADR reviewer through the session-tap gateway first.

## Consequences

The canary produces an attributable gateway ledger row before wider rollout.
""",
        encoding="utf-8",
    )


class TestADRReviewerGatewayCanaryScenario:
    """Actual loop -> reviewer -> mint -> transit -> ledger -> routed output."""

    async def test_configured_canary_runs_through_gateway(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo_root = tmp_path / "repo"
        data_root = tmp_path / "data"
        ledger = GatewayLedger(data_root / "gateway" / "requests.jsonl")
        key_store = VirtualKeyStore(
            max_ttl_seconds=300,
            id_factory=lambda: "adr-canary-key",
            secret_factory=lambda: "adr-canary-virtual-secret",
        )
        origin = _FakeAnthropicOrigin()
        upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
        settings = GatewaySettings(
            control_token=SecretStr(_CONTROL_TOKEN),
            upstreams={
                ProviderBinding.ANTHROPIC: UpstreamSettings(
                    base_url="https://anthropic.test",
                    api_key=SecretStr(_PROVIDER_KEY),
                    auth_style=UpstreamAuthStyle.X_API_KEY,
                )
            },
            ledger_path=ledger.path,
            body_dir=data_root / "gateway" / "bodies",
            max_key_ttl_seconds=300,
        )
        gateway = create_app(
            settings,
            key_store=key_store,
            client=upstream_client,
            ledger=ledger,
        )
        bin_dir = tmp_path / "bin"
        _write_claude_shim(bin_dir)
        _write_proposed_adr(repo_root)

        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-real-anthropic-key")
        monkeypatch.setenv("OPENAI_ADMIN_KEY", "ambient-real-admin-key")

        try:
            async with _serve(gateway) as gateway_url:
                config = HydraFlowConfig(
                    repo="acme/hydraflow",
                    repo_root=repo_root,
                    data_root=data_root,
                    workspace_base=tmp_path / "worktrees",
                    adr_review_provider="gateway",
                    adr_review_model="sonnet",
                    gateway_base_url=gateway_url,
                    gateway_repo_class="hydraflow",
                    gateway_capture_bodies=False,
                    gateway_key_ttl_seconds=300,
                    agent_timeout=60,
                    dry_run=True,
                )
                world = MockWorld(tmp_path, config=config)
                seed_ports(world, adr_reviewer_runner=HostRunner())

                stats = await world.run_with_loops(["adr_reviewer"], cycles=1)
        finally:
            await upstream_client.aclose()

        canary = stats["adr_reviewer"]
        assert canary is not None
        assert canary["reviewed"] == 1
        assert canary["rejected"] == 1
        assert canary["auto_triaged"] == 1
        assert canary["rounds_total"] == 1

        decisions = [
            json.loads(line)
            for line in config.data_path("memory", "adr_decisions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(decisions) == 1
        assert decisions[0]["type"] == "follow_up"
        assert "ADR-9001" in decisions[0]["title"]

        assert key_store.active_count == 0
        assert len(origin.exchanges) == 1
        exchange = origin.exchanges[0]
        assert exchange.headers["x-api-key"] == _PROVIDER_KEY
        assert "authorization" not in exchange.headers
        assert not any(value.startswith("hfgw_") for value in exchange.headers.values())
        assert exchange.headers["x-canary-control-present"] == "false"
        assert exchange.headers["x-canary-provider-key-present"] == "false"
        assert exchange.payload["model"] == "sonnet"
        assert "ADR Review Council" in exchange.payload["messages"][0]["content"]

        rows = ledger.read_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.key_id == "adr-canary-key"
        assert row.principal.kind == "spawn"
        assert row.principal.id == "adr_reviewer"
        assert row.repo_slug == config.repo_slug
        assert row.model_requested == "sonnet"
        assert row.model_served == "claude-sonnet-4-6"
        assert row.input_tokens == 29
        assert row.output_tokens == 41
        assert row.completed is True
        assert row.cost_unknown is False
        ledger_text = ledger.path.read_text(encoding="utf-8")
        assert _CONTROL_TOKEN not in ledger_text
        assert _PROVIDER_KEY not in ledger_text
        assert "adr-canary-virtual-secret" not in ledger_text

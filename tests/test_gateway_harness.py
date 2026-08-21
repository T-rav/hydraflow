"""Gateway harness transport, minting, and host credential-isolation tests."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import HydraFlowConfig
from execution import SimpleResult
from runner_utils import (
    GatewayMintCredential,
    GatewayMintError,
    GatewayMintRequest,
    StreamConfig,
    _claude_cli_complete,
    _HttpGatewayControlClient,
    harness_billing_provider,
    renew_gateway_key_if_needed,
    resolve_harness_env,
    revoke_gateway_key,
    stream_claude_with_telemetry,
)
from subprocess_util import gateway_sensitive_env_keys


@dataclass
class _FakeGatewayClient:
    calls: list[tuple[str, str, GatewayMintRequest]] = field(default_factory=list)
    revocations: list[tuple[str, str, str]] = field(default_factory=list)
    credentials: list[GatewayMintCredential] = field(
        default_factory=lambda: [
            GatewayMintCredential(
                key_id="key-1",
                token="hfgw_virtual-1",
                expires_at="2099-08-19T12:05:00Z",
            )
        ]
    )
    revoke_acknowledged: bool = True

    async def mint_key(
        self,
        *,
        base_url: str,
        control_token: str,
        request: GatewayMintRequest,
    ) -> GatewayMintCredential:
        self.calls.append((base_url, control_token, request))
        return self.credentials[min(len(self.calls) - 1, len(self.credentials) - 1)]

    async def revoke_key(
        self,
        *,
        base_url: str,
        control_token: str,
        key_id: str,
    ) -> bool:
        self.revocations.append((base_url, control_token, key_id))
        return self.revoke_acknowledged


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "key_id": "key-malformed-expiry",
            "token": "virtual-token",
            "expires_at": "not-a-timestamp",
        },
        {
            "key_id": "key-incomplete-token",
            "expires_at": "2099-01-01T00:00:00Z",
        },
    ],
)
async def test_http_mint_revokes_issued_key_when_response_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=payload)
        return httpx.Response(
            200,
            json={"key_id": payload["key_id"], "revoked": True},
        )

    real_client = httpx.AsyncClient

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    client = _HttpGatewayControlClient()

    with pytest.raises(GatewayMintError, match="invalid response"):
        await client.mint_key(
            base_url="http://gateway:8080",
            control_token="control-secret",
            request=GatewayMintRequest(
                principal_kind="spawn",
                principal_id="implementer",
                spawn_id="spawn-1",
                session_id=None,
                repo_slug="org/repo",
                repo_class="personal",
                provider_binding="anthropic",
                capture_bodies=False,
                ttl_seconds=300,
            ),
        )

    assert [request.method for request in requests] == ["POST", "DELETE"]
    assert requests[-1].url.path == f"/control/v1/keys/{payload['key_id']}"


@pytest.mark.asyncio
async def test_http_malformed_mint_reports_unacknowledged_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "key_id": "key-cleanup-fails",
                    "token": "virtual-token",
                    "expires_at": "malformed",
                },
            )
        return httpx.Response(
            200,
            json={"key_id": "key-cleanup-fails", "revoked": False},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    with pytest.raises(GatewayMintError, match="invalid response"):
        await _HttpGatewayControlClient().mint_key(
            base_url="http://gateway:8080",
            control_token="control-secret",
            request=GatewayMintRequest(
                principal_kind="spawn",
                principal_id="implementer",
                spawn_id="spawn-1",
                session_id=None,
                repo_slug="org/repo",
                repo_class="personal",
                provider_binding="anthropic",
                capture_bodies=False,
                ttl_seconds=300,
            ),
        )

    assert [request.method for request in requests] == ["POST", "DELETE"]
    assert "gateway invalid-mint cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_gateway_mint_builds_bound_spawn_request_and_virtual_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    config = HydraFlowConfig(
        gateway_base_url="http://gateway:8080",
        gateway_repo_class="hydraflow",
        gateway_capture_bodies=True,
        gateway_key_ttl_seconds=300,
    )
    client = _FakeGatewayClient()

    env = await resolve_harness_env(
        "gateway",
        config,
        model="sonnet",
        source="adr_reviewer",
        session_id="session-7",
        spawn_id="spawn-9",
        gateway_client=client,
    )

    assert env == {
        "ANTHROPIC_BASE_URL": "http://gateway:8080",
        "ANTHROPIC_AUTH_TOKEN": "hfgw_virtual-1",
        "ANTHROPIC_API_KEY": "",
    }
    assert env.transport == "gateway"  # type: ignore[attr-defined]
    assert env.key_id == "key-1"  # type: ignore[attr-defined]
    assert env.expires_at == "2099-08-19T12:05:00Z"  # type: ignore[attr-defined]
    assert "hfgw_virtual-1" not in repr(env)
    assert "hfgw_virtual-1" not in repr(client.credentials[0])
    assert "control-secret" not in repr(env)
    assert len(client.calls) == 1
    base_url, control_token, request = client.calls[0]
    assert base_url == "http://gateway:8080"
    assert control_token == "control-secret"
    assert request == GatewayMintRequest(
        principal_kind="spawn",
        principal_id="adr_reviewer",
        spawn_id="spawn-9",
        session_id="session-7",
        repo_slug=config.repo_slug,
        repo_class="hydraflow",
        provider_binding="anthropic",
        capture_bodies=True,
        ttl_seconds=300,
    )

    await revoke_gateway_key(env)
    assert client.revocations == [("http://gateway:8080", "control-secret", "key-1")]


@pytest.mark.asyncio
async def test_gateway_ttl_covers_full_spawn_timeout_and_fast_retry_reuses_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient()

    env = await resolve_harness_env(
        "gateway",
        HydraFlowConfig(gateway_key_ttl_seconds=300),
        model="sonnet",
        source="implementer",
        timeout_seconds=3600,
        gateway_client=client,
    )
    renewed = await renew_gateway_key_if_needed(
        env,
        min_validity_seconds=3600,
    )

    assert client.calls[0][2].ttl_seconds == 3660
    assert renewed is False
    assert len(client.calls) == 1
    await revoke_gateway_key(env)


@pytest.mark.asyncio
async def test_gateway_expiring_lease_remints_once_and_revokes_both_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient(
        credentials=[
            GatewayMintCredential(
                key_id="expired-key",
                token="hfgw_expired",
                expires_at="2000-01-01T00:00:00Z",
            ),
            GatewayMintCredential(
                key_id="renewed-key",
                token="hfgw_renewed",
                expires_at="2099-01-01T00:00:00Z",
            ),
        ]
    )
    env = await resolve_harness_env(
        "gateway",
        HydraFlowConfig(),
        model="sonnet",
        source="implementer",
        timeout_seconds=3600,
        gateway_client=client,
    )

    renewed = await renew_gateway_key_if_needed(
        env,
        min_validity_seconds=3600,
    )

    assert renewed is True
    assert len(client.calls) == 2
    assert env["ANTHROPIC_AUTH_TOKEN"] == "hfgw_renewed"
    assert env.key_id == "renewed-key"  # type: ignore[attr-defined]
    assert client.revocations == [
        ("http://127.0.0.1:8080", "control-secret", "expired-key")
    ]

    await revoke_gateway_key(env)
    assert client.revocations[-1] == (
        "http://127.0.0.1:8080",
        "control-secret",
        "renewed-key",
    )


@pytest.mark.asyncio
async def test_gateway_final_revoke_requires_positive_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient(revoke_acknowledged=False)
    env = await resolve_harness_env(
        "gateway",
        HydraFlowConfig(),
        model="sonnet",
        source="implementer",
        gateway_client=client,
    )

    await revoke_gateway_key(env)
    await revoke_gateway_key(env)

    assert len(client.revocations) == 2
    assert "gateway key revocation failed" in caplog.text


@pytest.mark.asyncio
async def test_gateway_renewal_reports_unacknowledged_superseded_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient(
        credentials=[
            GatewayMintCredential(
                key_id="expired-key",
                token="hfgw_expired",
                expires_at="2000-01-01T00:00:00Z",
            ),
            GatewayMintCredential(
                key_id="renewed-key",
                token="hfgw_renewed",
                expires_at="2099-01-01T00:00:00Z",
            ),
        ],
        revoke_acknowledged=False,
    )
    env = await resolve_harness_env(
        "gateway",
        HydraFlowConfig(),
        model="sonnet",
        source="implementer",
        timeout_seconds=3600,
        gateway_client=client,
    )

    renewed = await renew_gateway_key_if_needed(
        env,
        min_validity_seconds=3600,
    )

    assert renewed is True
    assert env["ANTHROPIC_AUTH_TOKEN"] == "hfgw_renewed"
    assert client.revocations == [
        ("http://127.0.0.1:8080", "control-secret", "expired-key")
    ]
    assert "gateway superseded-key revocation failed" in caplog.text


@pytest.mark.asyncio
async def test_streaming_gateway_spawn_revokes_key_in_finally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient()
    event_bus = MagicMock()
    event_bus.current_session_id = "session-1"

    with (
        patch("runner_utils._HttpGatewayControlClient", return_value=client),
        patch(
            "runner_utils.stream_claude_process",
            new_callable=AsyncMock,
            return_value="complete",
        ),
        patch("runner_utils.record_inference_telemetry") as record_mock,
    ):
        transcript = await stream_claude_with_telemetry(
            config=HydraFlowConfig(gateway_base_url="http://gateway:8080"),
            cmd=["claude", "--model", "sonnet", "-p"],
            prompt="hello",
            cwd=tmp_path,
            active_procs=set(),
            event_bus=event_bus,
            event_data={"source": "implementer"},
            logger=logging.getLogger("test"),
            stream_config=StreamConfig(timeout=10),
            provider="gateway",
        )

    assert transcript == "complete"
    assert len(client.calls) == 1
    assert client.revocations == [("http://gateway:8080", "control-secret", "key-1")]
    assert record_mock.call_args.kwargs["cmd"] == [
        "gateway",
        "--model",
        "sonnet",
    ]


@pytest.mark.asyncio
async def test_gateway_glm_mint_keeps_gateway_transport_but_binds_zai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient()

    await resolve_harness_env(
        "gateway",
        HydraFlowConfig(implementation_provider="gateway", model="glm-5.2"),
        model="glm-5.2",
        source="implementer",
        gateway_client=client,
    )

    assert client.calls[0][2].provider_binding == "zai-harness"
    assert harness_billing_provider("gateway", "glm-5.2") == "zai"
    assert harness_billing_provider("gateway", "sonnet") == "claude"


@pytest.mark.asyncio
async def test_gateway_missing_control_token_fails_closed_before_mint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", raising=False)
    client = _FakeGatewayClient()

    with pytest.raises(GatewayMintError, match="CONTROL_TOKEN is unset"):
        await resolve_harness_env(
            "gateway",
            HydraFlowConfig(),
            model="sonnet",
            source="adr_reviewer",
            gateway_client=client,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_gateway_host_spawn_scrubs_real_and_admin_credentials_before_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in gateway_sensitive_env_keys():
        monkeypatch.setenv(key, f"real-{key.lower()}")
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GH_TOKEN", "ghp-worker-needs-this")
    defensive_keys = {
        "UNREGISTERED_LLM_API_KEY": "unknown-provider-secret",
        "OPENAI_ADMIN_KEY": "admin-secret",
        "AWS_ACCESS_KEY_ID": "aws-key",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "AWS_SESSION_TOKEN": "aws-session",
        "AWS_PROFILE": "bedrock-profile",
        "AWS_SHARED_CREDENTIALS_FILE": "/secrets/aws",
        "GOOGLE_APPLICATION_CREDENTIALS": "/secrets/gcp.json",
        "AZURE_CLIENT_SECRET": "azure-secret",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "1",
        "CLAUDE_CODE_USE_FOUNDRY": "1",
        "ANTHROPIC_VERTEX_PROJECT_ID": "vertex-project",
    }
    for key, value in defensive_keys.items():
        monkeypatch.setenv(key, value)
    captured: dict[str, str] = {}

    class _Runner:
        async def run_simple(
            self, _cmd: Any, *, env: dict[str, str], **_: Any
        ) -> SimpleResult:
            captured.update(env)
            return SimpleResult(stdout="ok", returncode=0)

    client = _FakeGatewayClient()
    result = await _claude_cli_complete(
        runner=_Runner(),  # type: ignore[arg-type]
        tool="claude",
        model="sonnet",
        prompt="hello",
        timeout=10,
        gh_token="",
        isolate_user_settings=True,
        provider="gateway",
        config=HydraFlowConfig(gateway_base_url="http://gateway:8080"),
        source="adr_reviewer",
        gateway_client=client,
    )

    assert result.returncode == 0
    assert client.revocations == [("http://gateway:8080", "control-secret", "key-1")]
    assert captured["ANTHROPIC_BASE_URL"] == "http://gateway:8080"
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "hfgw_virtual-1"
    assert captured["ANTHROPIC_API_KEY"] == ""
    assert captured["PATH"] == "/usr/bin"
    assert captured["GH_TOKEN"] == "ghp-worker-needs-this"
    for key in gateway_sensitive_env_keys() - {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    }:
        assert key not in captured
    for key in defensive_keys:
        assert key not in captured


@pytest.mark.asyncio
async def test_gateway_lightweight_spawn_revokes_key_when_runner_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient()

    class _FailingRunner:
        async def run_simple(self, *_args: Any, **_kwargs: Any) -> SimpleResult:
            raise RuntimeError("worker failed")

    with pytest.raises(RuntimeError, match="worker failed"):
        await _claude_cli_complete(
            runner=_FailingRunner(),  # type: ignore[arg-type]
            tool="claude",
            model="sonnet",
            prompt="hello",
            timeout=10,
            gh_token="",
            isolate_user_settings=True,
            provider="gateway",
            config=HydraFlowConfig(gateway_base_url="http://gateway:8080"),
            source="adr_reviewer",
            gateway_client=client,
        )

    assert client.revocations == [("http://gateway:8080", "control-secret", "key-1")]


@pytest.mark.asyncio
async def test_gateway_mint_threads_issue_and_pr_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    config = HydraFlowConfig(
        gateway_base_url="http://gateway:8080", gateway_key_ttl_seconds=300
    )
    client = _FakeGatewayClient()

    env = await resolve_harness_env(
        "gateway",
        config,
        model="sonnet",
        source="implementer",
        spawn_id="spawn-9",
        issue_number=11464,
        pr_number=11500,
        gateway_client=client,
    )
    await revoke_gateway_key(env)

    (_, _, request) = client.calls[0]
    assert request.issue_number == 11464
    assert request.pr_number == 11500


@pytest.mark.asyncio
async def test_gateway_mint_attribution_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    config = HydraFlowConfig(
        gateway_base_url="http://gateway:8080", gateway_key_ttl_seconds=300
    )
    client = _FakeGatewayClient()

    env = await resolve_harness_env(
        "gateway", config, model="sonnet", spawn_id="spawn-9", gateway_client=client
    )
    await revoke_gateway_key(env)

    (_, _, request) = client.calls[0]
    assert request.issue_number is None
    assert request.pr_number is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attribution",
    [
        pytest.param({"issue_number": 11464, "pr_number": 11500}, id="attributed"),
        pytest.param({}, id="unattributed-omits-keys"),
    ],
)
async def test_http_mint_payload_carries_attribution_only_when_present(
    monkeypatch: pytest.MonkeyPatch, attribution: dict[str, int]
) -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            201,
            json={
                "key_id": "key-1",
                "token": "hfgw_virtual",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    credential = await _HttpGatewayControlClient().mint_key(
        base_url="http://gateway:8080",
        control_token="control-secret",
        request=GatewayMintRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id=None,
            repo_slug="org/repo",
            repo_class="personal",
            provider_binding="anthropic",
            capture_bodies=False,
            ttl_seconds=300,
            **attribution,
        ),
    )

    assert credential.key_id == "key-1"
    (body,) = bodies
    # An older gateway rejects unknown keys (extra="forbid"): only send what is set.
    for key in ("issue_number", "pr_number"):
        if key in attribution:
            assert body[key] == attribution[key]
        else:
            assert key not in body


@pytest.mark.asyncio
async def test_stream_with_telemetry_threads_attribution_into_gateway_mint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The central telemetry wrapper already knows the issue/PR; the mint must too."""
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    client = _FakeGatewayClient()
    bus = MagicMock()
    bus.current_session_id = "session-7"

    with (
        patch("runner_utils._HttpGatewayControlClient", return_value=client),
        patch(
            "runner_utils.stream_claude_process",
            new_callable=AsyncMock,
            return_value="transcript",
        ),
        patch("runner_utils.record_inference_telemetry"),
    ):
        await stream_claude_with_telemetry(
            config=HydraFlowConfig(gateway_base_url="http://gateway:8080"),
            cmd=["claude", "--model", "sonnet", "-p"],
            prompt="prompt",
            cwd=tmp_path,
            active_procs=set(),
            event_bus=bus,
            event_data={"issue": 42, "pr": 77, "source": "implementer"},
            logger=logging.getLogger("test"),
            provider="gateway",
        )

    (_, _, request) = client.calls[0]
    assert request.issue_number == 42
    assert request.pr_number == 77

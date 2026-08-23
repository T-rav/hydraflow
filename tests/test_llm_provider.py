"""Tests for the pluggable one-shot LLM provider seam in runner_utils.

Covers the OpenAI-compatible HTTP backends (OpenRouter and z.ai) — request/
response mapping, per-backend base URL + secret-key resolution, credit
detection, JSON-schema parity — and the provider dispatch inside
run_lightweight_agent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from runner_utils import (
    _OPENAI_COMPAT_BACKENDS,
    _openai_compatible_complete,
    _telemetry_cmd,
    provider_key_presence,
)
from subprocess_util import CreditExhaustedError


class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise json.JSONDecodeError("no json", "", 0)
        return self._json


class _FakeClient:
    """Records the request and returns a canned response."""

    calls: list[dict] = []

    def __init__(self, resp, **_kw):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, url, *, json=None, headers=None):
        _FakeClient.calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _patch_httpx(monkeypatch, resp):
    _FakeClient.calls = []

    def _factory(**kw):
        return _FakeClient(resp, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _ok(content="hello", usage=None):
    return _FakeResp(
        json_data={"choices": [{"message": {"content": content}}], "usage": usage or {}}
    )


class TestTelemetryCmd:
    @pytest.mark.parametrize(
        ("head", "model"),
        [
            pytest.param(
                "openrouter", "deepseek/x", id="test_openrouter_head_is_provider_name"
            ),
            # z.ai gets its own attribution bucket on the cost dashboard.
            pytest.param("zai", "glm-4.6", id="test_zai_head_is_provider_name"),
            # kimi (Moonshot) gets its own attribution bucket on the cost dashboard.
            pytest.param("kimi", "kimi-k3", id="test_kimi_head_is_provider_name"),
            pytest.param("claude", "haiku", id="test_claude_head_is_tool"),
            pytest.param(
                "gateway",
                "haiku",
                id="test_gateway_head_marks_transport_for_coverage_deduplication",
            ),
        ],
    )
    def test_telemetry_cmd_preserves_head_and_model(self, head, model):
        assert _telemetry_cmd(head, "claude", model) == [head, "--model", model]


class TestBackendRegistry:
    """Each OpenAI-compatible backend resolves a base URL (from config) and a
    secret API key (from the environment only)."""

    def test_openrouter_reads_openrouter_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-123")
        assert _OPENAI_COMPAT_BACKENDS["openrouter"].api_key() == "sk-or-123"

    def test_openrouter_falls_back_to_hydraflow_prefixed(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("HYDRAFLOW_OPENROUTER_API_KEY", "sk-hf")
        assert _OPENAI_COMPAT_BACKENDS["openrouter"].api_key() == "sk-hf"

    def test_zai_reads_zai_env(self, monkeypatch):
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-123")
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == "sk-zai-123"

    def test_zai_falls_back_to_hydraflow_prefixed(self, monkeypatch):
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.setenv("HYDRAFLOW_ZAI_API_KEY", "sk-zai-hf")
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == "sk-zai-hf"

    def test_kimi_reads_moonshot_env(self, monkeypatch):
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi-123")
        assert _OPENAI_COMPAT_BACKENDS["kimi"].api_key() == "sk-kimi-123"

    def test_kimi_falls_back_to_kimi_then_hydraflow_prefixed(self, monkeypatch):
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        monkeypatch.setenv("KIMI_API_KEY", "sk-kimi-alias")
        assert _OPENAI_COMPAT_BACKENDS["kimi"].api_key() == "sk-kimi-alias"
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        monkeypatch.setenv("HYDRAFLOW_KIMI_API_KEY", "sk-kimi-hf")
        assert _OPENAI_COMPAT_BACKENDS["kimi"].api_key() == "sk-kimi-hf"

    def test_backends_do_not_cross_read_keys(self, monkeypatch):
        # Each backend's key must satisfy only that backend, never a sibling.
        for env in (
            "OPENROUTER_API_KEY",
            "HYDRAFLOW_OPENROUTER_API_KEY",
            "MOONSHOT_API_KEY",
            "KIMI_API_KEY",
            "HYDRAFLOW_KIMI_API_KEY",
        ):
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-only")
        assert _OPENAI_COMPAT_BACKENDS["openrouter"].api_key() == ""
        assert _OPENAI_COMPAT_BACKENDS["kimi"].api_key() == ""
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == "sk-zai-only"

    def test_empty_when_unset(self, monkeypatch):
        for env in (
            "OPENROUTER_API_KEY",
            "HYDRAFLOW_OPENROUTER_API_KEY",
            "ZAI_API_KEY",
            "HYDRAFLOW_ZAI_API_KEY",
            "MOONSHOT_API_KEY",
            "KIMI_API_KEY",
            "HYDRAFLOW_KIMI_API_KEY",
        ):
            monkeypatch.delenv(env, raising=False)
        assert _OPENAI_COMPAT_BACKENDS["openrouter"].api_key() == ""
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == ""
        assert _OPENAI_COMPAT_BACKENDS["kimi"].api_key() == ""

    def test_base_url_reads_the_backends_config_field(self):
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        assert (
            _OPENAI_COMPAT_BACKENDS["openrouter"].base_url(config)
            == config.openrouter_base_url
        )
        assert _OPENAI_COMPAT_BACKENDS["zai"].base_url(config) == config.zai_base_url
        assert _OPENAI_COMPAT_BACKENDS["kimi"].base_url(config) == config.kimi_base_url


class TestZaiCodingPlanKeySplit:
    """Two-key lane split: the harness (agentic Claude-CLI) lane prefers the
    flat-rate ZAI_CODING_PLAN_KEY; the one-shot REST lane stays on
    ZAI_API_KEY so background traffic never eats the plan quota."""

    _ALL = (
        "ZAI_CODING_PLAN_KEY",
        "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
        "ZAI_API_KEY",
        "HYDRAFLOW_ZAI_API_KEY",
    )

    def _clear(self, monkeypatch):
        for env in self._ALL:
            monkeypatch.delenv(env, raising=False)

    def test_harness_prefers_coding_plan_key(self, monkeypatch):
        from runner_utils import _HARNESS_BACKENDS

        self._clear(monkeypatch)
        monkeypatch.setenv("ZAI_API_KEY", "sk-api")
        monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "sk-plan")
        assert _HARNESS_BACKENDS["zai"].api_key() == "sk-plan"

    def test_harness_falls_back_to_api_key(self, monkeypatch):
        from runner_utils import _HARNESS_BACKENDS

        self._clear(monkeypatch)
        monkeypatch.setenv("ZAI_API_KEY", "sk-api")
        assert _HARNESS_BACKENDS["zai"].api_key() == "sk-api"

    def test_rest_lane_ignores_coding_plan_key(self, monkeypatch):
        """Background one-shot traffic must NEVER bill the coding plan."""
        self._clear(monkeypatch)
        monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "sk-plan")
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == ""
        monkeypatch.setenv("ZAI_API_KEY", "sk-api")
        assert _OPENAI_COMPAT_BACKENDS["zai"].api_key() == "sk-api"

    def test_probe_follows_harness_key_when_split(self, monkeypatch):
        """#11267 review find: a plan-quota cap must be corroborated against
        the PLAN credential — probing the REST key would falsely refute it
        (probe healthy -> signal discarded -> retry storm)."""
        from runner_utils import backend_probe_endpoint
        from tests.helpers import ConfigFactory

        self._clear(monkeypatch)
        config = ConfigFactory.create()
        monkeypatch.setenv("ZAI_API_KEY", "sk-api")
        monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "sk-plan")
        base_url, key = backend_probe_endpoint("zai", config)
        assert key == "sk-plan"
        assert base_url == config.zai_harness_base_url

        # Single-key setups keep the pre-split REST probe pair.
        monkeypatch.delenv("ZAI_CODING_PLAN_KEY", raising=False)
        base_url, key = backend_probe_endpoint("zai", config)
        assert key == "sk-api"
        assert base_url == config.zai_base_url

    def test_failover_enabled_by_plan_key_alone(self, monkeypatch):
        from credit_failover import zai_key_present

        self._clear(monkeypatch)
        assert zai_key_present() is False
        monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "sk-plan")
        assert zai_key_present() is True


class TestProviderKeyPresence:
    """The UI badge source: which backends have their secret key set — booleans
    only, keyed by provider name, never the value."""

    def _clear(self, monkeypatch):
        for env in (
            "OPENROUTER_API_KEY",
            "HYDRAFLOW_OPENROUTER_API_KEY",
            "ZAI_API_KEY",
            "HYDRAFLOW_ZAI_API_KEY",
            "MOONSHOT_API_KEY",
            "KIMI_API_KEY",
            "HYDRAFLOW_KIMI_API_KEY",
        ):
            monkeypatch.delenv(env, raising=False)

    def test_reports_a_bool_per_backend(self, monkeypatch):
        self._clear(monkeypatch)
        presence = provider_key_presence()
        assert set(presence) == set(_OPENAI_COMPAT_BACKENDS)
        assert all(isinstance(v, bool) for v in presence.values())

    def test_true_only_for_the_backend_whose_key_is_set(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai")
        presence = provider_key_presence()
        assert presence["zai"] is True
        assert presence["openrouter"] is False
        assert presence["kimi"] is False

    def test_all_false_when_unset(self, monkeypatch):
        self._clear(monkeypatch)
        assert provider_key_presence() == {
            "openrouter": False,
            "zai": False,
            "kimi": False,
        }


@pytest.mark.asyncio
class TestOpenAICompatibleComplete:
    async def _run(self, monkeypatch, resp, *, provider="openrouter", **kw):
        _patch_httpx(monkeypatch, resp)
        return await _openai_compatible_complete(
            provider=provider,
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            model="deepseek/deepseek-chat",
            prompt="classify this",
            timeout=30.0,
            **kw,
        )

    async def test_happy_path_returns_content(self, monkeypatch):
        result = await self._run(monkeypatch, _ok("VERDICT: ok"))
        assert result.returncode == 0
        assert result.stdout == "VERDICT: ok"
        # Request went to the chat/completions endpoint with the model + prompt.
        req = _FakeClient.calls[0]
        assert req["url"].endswith("/chat/completions")
        assert req["json"]["model"] == "deepseek/deepseek-chat"
        assert req["json"]["messages"][0]["content"] == "classify this"
        assert req["headers"]["Authorization"] == "Bearer sk-or-test"

    async def test_zai_happy_path_same_shape(self, monkeypatch):
        # z.ai speaks the identical OpenAI-compatible shape.
        result = await self._run(monkeypatch, _ok("glm says hi"), provider="zai")
        assert result.returncode == 0
        assert result.stdout == "glm says hi"
        assert _FakeClient.calls[0]["url"].endswith("/chat/completions")

    async def test_response_schema_sets_json_mode(self, monkeypatch):
        schema = {"type": "object", "properties": {"ready": {"type": "boolean"}}}
        await self._run(monkeypatch, _ok("{}"), response_schema=schema)
        rf = _FakeClient.calls[0]["json"]["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["schema"] == schema
        assert rf["json_schema"]["strict"] is True

    async def test_no_schema_omits_response_format(self, monkeypatch):
        await self._run(monkeypatch, _ok())
        assert "response_format" not in _FakeClient.calls[0]["json"]

    async def test_missing_api_key_soft_fails(self, monkeypatch):
        _patch_httpx(monkeypatch, _ok())
        result = await _openai_compatible_complete(
            provider="zai",
            base_url="https://x",
            api_key="",
            model="m",
            prompt="p",
            timeout=5.0,
        )
        assert result.returncode == -1
        # Error is labeled with the provider whose key is missing.
        assert "zai" in result.stderr
        assert "API key is not set" in result.stderr
        assert not _FakeClient.calls  # never made the request

    async def test_429_raises_credit_exhausted(self, monkeypatch):
        with pytest.raises(CreditExhaustedError):
            await self._run(monkeypatch, _FakeResp(status_code=429, text="rate limit"))

    async def test_402_raises_credit_exhausted(self, monkeypatch):
        with pytest.raises(CreditExhaustedError):
            await self._run(
                monkeypatch, _FakeResp(status_code=402, text="insufficient credits")
            )

    async def test_400_with_credit_body_raises(self, monkeypatch):
        # A non-402/429 error whose body signals exhaustion still pauses.
        with pytest.raises(CreditExhaustedError):
            await self._run(
                monkeypatch,
                _FakeResp(status_code=400, text="You've hit your usage limit"),
            )

    async def test_429_tags_signal_with_this_backend(self, monkeypatch):
        # #9807: the raised signal carries THIS backend so the orchestrator can
        # scope the pause to z.ai/kimi loops instead of halting Claude work.
        with pytest.raises(CreditExhaustedError) as exc_info:
            await self._run(
                monkeypatch,
                _FakeResp(status_code=429, text="rate limit"),
                provider="zai",
            )
        assert exc_info.value.provider == "zai"

    async def test_402_tags_signal_with_this_backend(self, monkeypatch):
        with pytest.raises(CreditExhaustedError) as exc_info:
            await self._run(
                monkeypatch,
                _FakeResp(status_code=402, text="insufficient credits"),
                provider="kimi",
            )
        assert exc_info.value.provider == "kimi"

    async def test_400_credit_body_tags_signal_with_this_backend(self, monkeypatch):
        with pytest.raises(CreditExhaustedError) as exc_info:
            await self._run(
                monkeypatch,
                _FakeResp(status_code=400, text="You've hit your usage limit"),
                provider="openrouter",
            )
        assert exc_info.value.provider == "openrouter"

    async def test_other_http_error_soft_fails_labeled_by_provider(self, monkeypatch):
        result = await self._run(
            monkeypatch, _FakeResp(status_code=500, text="server boom"), provider="zai"
        )
        assert result.returncode == 500
        assert "zai http 500" in result.stderr

    async def test_captures_real_token_usage(self, monkeypatch):
        usage: dict = {}
        _patch_httpx(
            monkeypatch,
            _ok(
                "hi",
                usage={
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            ),
        )
        await _openai_compatible_complete(
            provider="openrouter",
            base_url="https://x",
            api_key="k",
            model="m",
            prompt="p",
            timeout=5.0,
            usage_out=usage,
        )
        assert usage == {
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "usage_available": True,
        }

    async def test_usage_available_false_when_api_omits_usage(self, monkeypatch):
        usage: dict = {}
        _patch_httpx(monkeypatch, _ok("hi", usage={}))
        await _openai_compatible_complete(
            provider="openrouter",
            base_url="https://x",
            api_key="k",
            model="m",
            prompt="p",
            timeout=5.0,
            usage_out=usage,
        )
        assert usage["usage_available"] is False
        assert usage["total_tokens"] == 0

    async def test_malformed_response_soft_fails(self, monkeypatch):
        result = await self._run(monkeypatch, _FakeResp(json_data={"nope": 1}))
        assert result.returncode == -1
        assert "malformed" in result.stderr

    async def test_timeout_becomes_timeouterror(self, monkeypatch):
        with pytest.raises(TimeoutError):
            await self._run(monkeypatch, httpx.TimeoutException("slow"))


@pytest.mark.asyncio
class TestRunLightweightAgentDispatch:
    """The seam picks the backend from ``provider`` and still records telemetry
    with the right (tool, model) descriptor."""

    async def test_openrouter_provider_routes_to_http(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        calls = {"n": 0}

        async def _fake_complete(**kwargs):
            calls["n"] += 1
            calls["kwargs"] = kwargs
            return SimpleResult(stdout="OR-RESULT", returncode=0)

        monkeypatch.setattr("runner_utils._openai_compatible_complete", _fake_complete)

        config = ConfigFactory.create()
        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=config,
            tool="claude",
            model="deepseek/deepseek-chat",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="openrouter",
        )
        assert result.stdout == "OR-RESULT"
        assert calls["n"] == 1
        assert calls["kwargs"]["provider"] == "openrouter"
        assert calls["kwargs"]["base_url"] == config.openrouter_base_url
        assert calls["kwargs"]["model"] == "deepseek/deepseek-chat"

    async def test_zai_provider_routes_to_http_with_zai_base_url(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        calls = {"n": 0}

        async def _fake_complete(**kwargs):
            calls["n"] += 1
            calls["kwargs"] = kwargs
            return SimpleResult(stdout="ZAI-RESULT", returncode=0)

        monkeypatch.setattr("runner_utils._openai_compatible_complete", _fake_complete)

        config = ConfigFactory.create()
        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=config,
            tool="claude",
            model="glm-4.6",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="zai",
        )
        assert result.stdout == "ZAI-RESULT"
        assert calls["n"] == 1
        assert calls["kwargs"]["provider"] == "zai"
        # The z.ai backend uses its OWN base URL, not openrouter's.
        assert calls["kwargs"]["base_url"] == config.zai_base_url

    async def test_openrouter_real_usage_flows_to_telemetry(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        async def _fake_complete(*, usage_out=None, **_kw):
            if usage_out is not None:
                usage_out.update(
                    {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "usage_available": True,
                    }
                )
            return SimpleResult(stdout="ok", returncode=0)

        recorded: dict = {}

        def _fake_record(_config, **kw):
            recorded.update(kw)

        monkeypatch.setattr("runner_utils._openai_compatible_complete", _fake_complete)
        monkeypatch.setattr("runner_utils.record_inference_telemetry", _fake_record)

        await run_lightweight_agent(
            runner=AsyncMock(),
            config=ConfigFactory.create(),
            tool="claude",
            model="deepseek/deepseek-chat",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="openrouter",
        )
        # Real API usage reached the telemetry record → token_source="actual".
        assert recorded["stats"]["total_tokens"] == 120
        assert recorded["stats"]["usage_available"] is True

    async def test_default_provider_stays_claude_cli(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        http_called = {"n": 0}
        cli_called = {"n": 0}

        async def _fake_complete(**_kw):
            http_called["n"] += 1
            return SimpleResult(returncode=0)

        async def _fake_cli(**_kw):
            cli_called["n"] += 1
            return SimpleResult(stdout="CLI", returncode=0)

        monkeypatch.setattr("runner_utils._openai_compatible_complete", _fake_complete)
        monkeypatch.setattr("runner_utils._claude_cli_complete", _fake_cli)

        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=ConfigFactory.create(),
            tool="claude",
            model="haiku",
            prompt="p",
            source="unit_test",
            timeout=10.0,
        )
        assert result.stdout == "CLI"
        assert cli_called["n"] == 1
        assert http_called["n"] == 0

    async def test_omitted_provider_inherits_maintenance_gateway(self, monkeypatch):
        from unittest.mock import AsyncMock

        from config import HydraFlowConfig
        from execution import SimpleResult
        from runner_utils import run_lightweight_agent

        cli_kwargs: dict = {}
        recorded: dict = {}

        async def _fake_cli(**kwargs):
            cli_kwargs.update(kwargs)
            return SimpleResult(stdout="gateway", returncode=0)

        def _fake_record(_config, **kwargs):
            recorded.update(kwargs)

        monkeypatch.setattr("runner_utils._claude_cli_complete", _fake_cli)
        monkeypatch.setattr("runner_utils.record_inference_telemetry", _fake_record)

        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=HydraFlowConfig(
                maintenance_provider="gateway",
                maintenance_model="glm-5.2",
            ),
            tool="claude",
            model="glm-5.2",
            prompt="p",
            source="sampled_audit",
            timeout=10.0,
        )

        assert result.stdout == "gateway"
        assert cli_kwargs["provider"] == "gateway"
        assert recorded["cmd"] == ["gateway", "--model", "glm-5.2"]

    async def test_explicit_provider_overrides_maintenance_provider(self, monkeypatch):
        from unittest.mock import AsyncMock

        from config import HydraFlowConfig
        from execution import SimpleResult
        from runner_utils import run_lightweight_agent

        cli_kwargs: dict = {}

        async def _fake_cli(**kwargs):
            cli_kwargs.update(kwargs)
            return SimpleResult(stdout="direct", returncode=0)

        monkeypatch.setattr("runner_utils._claude_cli_complete", _fake_cli)

        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=HydraFlowConfig(maintenance_provider="gateway"),
            tool="claude",
            model="sonnet",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="claude",
        )

        assert result.stdout == "direct"
        assert cli_kwargs["provider"] == "claude"

    async def test_terminal_gateway_replaces_host_runner_with_owned_docker_runner(
        self, monkeypatch
    ):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from config import HydraFlowConfig
        from execution import HostRunner, SimpleResult
        from gateway_mint_client import GatewayMintCredential
        from runner_utils import run_lightweight_agent

        isolated_runner = AsyncMock()
        isolated_runner.run_simple.return_value = SimpleResult(
            stdout="isolated",
            returncode=0,
        )
        gateway_client = AsyncMock()
        gateway_client.mint_key.return_value = GatewayMintCredential(
            key_id="terminal-long-prompt",
            token="hfgw_terminal_long_prompt",
            expires_at="2099-08-19T12:05:00Z",
        )
        gateway_client.revoke_key.return_value = True
        prompt = "p" * 100_001
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")

        monkeypatch.setattr(
            "runner_utils.get_docker_runner",
            lambda _config: isolated_runner,
        )
        monkeypatch.setattr(
            "runner_utils.record_inference_telemetry",
            lambda *_args, **_kwargs: None,
        )
        # The boundary under test is the large-prompt stdin handoff. Prompt
        # shape observation is intentionally exercised by its own suite and is
        # expensive for a 100 KiB synthetic string.
        monkeypatch.setattr(
            "runner_utils.gate_prompt",
            lambda prompt, **_kwargs: SimpleNamespace(prompt=prompt),
        )

        result = await run_lightweight_agent(
            runner=HostRunner(),
            config=HydraFlowConfig(
                gateway_fleet_ratchet_enabled=True,
                execution_mode="docker",
            ),
            tool="claude",
            model="haiku",
            prompt=prompt,
            source="sampled_audit",
            timeout=10.0,
            gateway_client=gateway_client,
        )

        assert result.stdout == "isolated"
        run_kwargs = isolated_runner.run_simple.await_args.kwargs
        assert run_kwargs["input"] == prompt.encode()
        assert run_kwargs["env"]["ANTHROPIC_AUTH_TOKEN"] == (
            "hfgw_terminal_long_prompt"
        )
        assert run_kwargs["env"]["ANTHROPIC_API_KEY"] == ""
        isolated_runner.cleanup.assert_awaited_once_with()
        gateway_client.revoke_key.assert_awaited_once()


class TestHarnessBackend:
    """z.ai as a Claude-harness backend (the /api/anthropic face)."""

    def test_zai_harness_base_url_default_and_lookup(self) -> None:
        from config import HydraFlowConfig
        from runner_utils import harness_base_url

        cfg = HydraFlowConfig()
        assert cfg.zai_harness_base_url == "https://api.z.ai/api/anthropic"
        assert harness_base_url("zai", cfg) == cfg.zai_harness_base_url
        # claude/anthropic are not harness *backends* — they use the native
        # Anthropic endpoint, so there is no override URL.
        assert harness_base_url("claude", cfg) == ""
        assert harness_base_url("anthropic", cfg) == ""
        assert harness_base_url("openrouter", cfg) == ""

    @pytest.mark.asyncio
    async def test_resolve_harness_env_isolation_and_zai(self, monkeypatch) -> None:
        from config import HydraFlowConfig
        from runner_utils import resolve_harness_env

        cfg = HydraFlowConfig()
        # Native Anthropic: pristine env — the main workers must stay untouched.
        assert await resolve_harness_env("claude", cfg) == {}
        assert await resolve_harness_env("anthropic", cfg) == {}
        # zai: point the Claude CLI at GLM + clear the shadowing API key.
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
        env = await resolve_harness_env("zai", cfg)
        assert env["ANTHROPIC_BASE_URL"] == cfg.zai_harness_base_url
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-zai-test"
        assert env["ANTHROPIC_API_KEY"] == ""

    @pytest.mark.asyncio
    async def test_resolve_harness_env_missing_key_falls_open(
        self, monkeypatch
    ) -> None:
        from config import HydraFlowConfig
        from runner_utils import resolve_harness_env

        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
        # No key → fall open to Anthropic rather than spawn a broken CLI.
        assert await resolve_harness_env("zai", HydraFlowConfig()) == {}

    @pytest.mark.asyncio
    async def test_cli_spawn_env_carries_zai_override(self, monkeypatch) -> None:
        from config import HydraFlowConfig
        from runner_utils import _claude_cli_complete

        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
        captured: dict[str, str] = {}

        class FakeRunner:
            async def run_simple(self, cmd, *, env, input, timeout):
                captured.update(env)
                from execution import SimpleResult

                return SimpleResult(stdout="ok", returncode=0)

        result = await _claude_cli_complete(
            runner=FakeRunner(),
            tool="claude",
            model="glm-5.2",
            prompt="p",
            timeout=1.0,
            gh_token="",
            isolate_user_settings=True,
            provider="zai",
            config=HydraFlowConfig(),
        )
        assert result.stdout == "ok"
        assert captured["ANTHROPIC_BASE_URL"].endswith("/api/anthropic")
        assert captured["ANTHROPIC_AUTH_TOKEN"] == "sk-zai-test"
        assert captured["ANTHROPIC_API_KEY"] == ""

    @pytest.mark.asyncio
    async def test_cli_spawn_env_pristine_for_claude(self, monkeypatch) -> None:
        from config import HydraFlowConfig
        from runner_utils import _claude_cli_complete

        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
        captured: dict[str, str] = {}

        class FakeRunner:
            async def run_simple(self, cmd, *, env, input, timeout):
                captured.update(env)
                from execution import SimpleResult

                return SimpleResult(stdout="ok", returncode=0)

        await _claude_cli_complete(
            runner=FakeRunner(),
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=1.0,
            gh_token="",
            isolate_user_settings=True,
            provider="claude",
            config=HydraFlowConfig(),
        )
        # The native provider gets no harness override — the isolation invariant
        # that keeps the main workers on Anthropic regardless of z.ai config.
        assert "ANTHROPIC_AUTH_TOKEN" not in captured


class TestUsageShapeStamp:
    """run_lightweight_agent stamps the shape of the usage it obtained."""

    async def test_one_shot_backend_stamps_openai_compat(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        async def _fake_complete(*, usage_out=None, **_kw):
            if usage_out is not None:
                usage_out.update({"input_tokens": 100, "output_tokens": 20})
            return SimpleResult(stdout="ok", returncode=0)

        recorded: dict = {}

        def _fake_record(_config, **kw):
            recorded.update(kw)

        monkeypatch.setenv("ZAI_API_KEY", "zai-key")
        monkeypatch.setattr("runner_utils._openai_compatible_complete", _fake_complete)
        monkeypatch.setattr("runner_utils.record_inference_telemetry", _fake_record)

        await run_lightweight_agent(
            runner=AsyncMock(),
            config=ConfigFactory.create(),
            tool="claude",
            model="glm-5.2",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="zai",
        )

        assert recorded["cmd"][0] == "zai"
        assert recorded["usage_shape"] == "openai_compat"

    async def test_claude_cli_path_stamps_anthropic(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        async def _fake_cli(**_kw):
            return SimpleResult(stdout="ok", returncode=0)

        recorded: dict = {}

        def _fake_record(_config, **kw):
            recorded.update(kw)

        monkeypatch.setattr("runner_utils._claude_cli_complete", _fake_cli)
        monkeypatch.setattr("runner_utils.record_inference_telemetry", _fake_record)

        await run_lightweight_agent(
            runner=AsyncMock(),
            config=ConfigFactory.create(),
            tool="claude",
            model="sonnet",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="claude",
        )

        assert recorded["cmd"][0] == "claude"
        assert recorded["usage_shape"] == "anthropic"

    @pytest.mark.parametrize(
        "cmd_head, expected_shape",
        [("claude", "anthropic"), ("gateway", "anthropic"), ("zai", "openai_compat")],
    )
    def test_record_inference_telemetry_derives_shape_from_cmd_head(
        self, tmp_path, cmd_head, expected_shape
    ):
        """Wrappers that omit ``usage_shape`` (e.g. contract_refresh) still
        stamp it from the cmd head, which for them is the real producer."""
        import json

        from runner_utils import record_inference_telemetry
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)

        record_inference_telemetry(
            config,
            source="contract_refresh",
            cmd=[cmd_head, "--model", "glm-5.2"],
            prompt="ping",
            transcript="pong",
            duration_s=0.1,
            success=True,
        )

        row = json.loads(config.cost_inferences_path.read_text().strip())
        assert row["tool"] == cmd_head
        assert row["usage_shape"] == expected_shape

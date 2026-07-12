"""Tests for the pluggable one-shot LLM provider seam in runner_utils.

Covers the OpenRouter HTTP backend (request/response mapping, credit detection,
JSON-schema parity) and the provider dispatch inside run_lightweight_agent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from runner_utils import (
    _openrouter_api_key,
    _openrouter_complete,
    _telemetry_cmd,
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
    def test_openrouter_head_is_provider_name(self):
        assert _telemetry_cmd("openrouter", "claude", "deepseek/x") == [
            "openrouter",
            "--model",
            "deepseek/x",
        ]

    def test_claude_head_is_tool(self):
        assert _telemetry_cmd("claude", "claude", "haiku") == [
            "claude",
            "--model",
            "haiku",
        ]


class TestApiKeyFromEnv:
    def test_reads_openrouter_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-123")
        assert _openrouter_api_key() == "sk-or-123"

    def test_falls_back_to_hydraflow_prefixed(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("HYDRAFLOW_OPENROUTER_API_KEY", "sk-hf")
        assert _openrouter_api_key() == "sk-hf"

    def test_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("HYDRAFLOW_OPENROUTER_API_KEY", raising=False)
        assert _openrouter_api_key() == ""


@pytest.mark.asyncio
class TestOpenRouterComplete:
    async def _run(self, monkeypatch, resp, **kw):
        _patch_httpx(monkeypatch, resp)
        return await _openrouter_complete(
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
        result = await _openrouter_complete(
            base_url="https://x", api_key="", model="m", prompt="p", timeout=5.0
        )
        assert result.returncode == -1
        assert "OPENROUTER_API_KEY" in result.stderr
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

    async def test_other_http_error_soft_fails(self, monkeypatch):
        result = await self._run(
            monkeypatch, _FakeResp(status_code=500, text="server boom")
        )
        assert result.returncode == 500
        assert "openrouter http 500" in result.stderr

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

        async def _fake_or(**kwargs):
            calls["n"] += 1
            calls["kwargs"] = kwargs
            return SimpleResult(stdout="OR-RESULT", returncode=0)

        monkeypatch.setattr("runner_utils._openrouter_complete", _fake_or)

        result = await run_lightweight_agent(
            runner=AsyncMock(),
            config=ConfigFactory.create(),
            tool="claude",
            model="deepseek/deepseek-chat",
            prompt="p",
            source="unit_test",
            timeout=10.0,
            provider="openrouter",
        )
        assert result.stdout == "OR-RESULT"
        assert calls["n"] == 1
        assert calls["kwargs"]["model"] == "deepseek/deepseek-chat"

    async def test_default_provider_stays_claude_cli(self, monkeypatch):
        from unittest.mock import AsyncMock

        from execution import SimpleResult
        from runner_utils import run_lightweight_agent
        from tests.helpers import ConfigFactory

        or_called = {"n": 0}
        cli_called = {"n": 0}

        async def _fake_or(**_kw):
            or_called["n"] += 1
            return SimpleResult(returncode=0)

        async def _fake_cli(**_kw):
            cli_called["n"] += 1
            return SimpleResult(stdout="CLI", returncode=0)

        monkeypatch.setattr("runner_utils._openrouter_complete", _fake_or)
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
        assert or_called["n"] == 0

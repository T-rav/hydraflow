"""Per-backend credit-pause isolation (#9807).

A Claude (Anthropic) credit cap must not halt z.ai/kimi background workers, and
a z.ai/kimi cap must not halt Claude work. These tests pin the three seams that
make that true:

  1. classification  — ``CreditExhaustedError.provider`` + ``normalize_provider``
  2. scoping         — ``_loop_providers`` / ``_affected_loops`` on the orchestrator
  3. probe-lift      — per-provider ``probe_credit_availability`` + endpoint resolution

The end-to-end classification-at-the-raise-site is pinned in test_llm_provider.py
(``_openai_compatible_complete`` tags the signal with its backend).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from orchestrator import HydraFlowOrchestrator
from runner_utils import backend_probe_endpoint, normalize_provider
from subprocess_util import (
    PROVIDER_ANTHROPIC,
    CreditExhaustedError,
    probe_credit_availability,
)
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# 1. Classification
# ---------------------------------------------------------------------------


class TestNormalizeProvider:
    def test_claude_dial_maps_to_anthropic(self) -> None:
        # The config dial spells the harness "claude"; the billing identity is
        # "anthropic" — this is the single reconciliation point.
        assert normalize_provider("claude") == "anthropic"

    @pytest.mark.parametrize("backend", ["zai", "kimi", "openrouter"])
    def test_backend_dials_map_to_themselves(self, backend: str) -> None:
        assert normalize_provider(backend) == backend

    def test_unknown_dial_falls_back_to_anthropic(self) -> None:
        # An unrecognized dial is treated as harness so it participates in the
        # (safe) global Anthropic pause rather than being silently exempted.
        assert normalize_provider("gemini") == "anthropic"
        assert normalize_provider("") == "anthropic"


class TestCreditExhaustedProvider:
    def test_defaults_to_anthropic(self) -> None:
        # Back-compat: every legacy raise site stays Anthropic-scoped.
        assert CreditExhaustedError("out").provider == PROVIDER_ANTHROPIC

    def test_carries_explicit_provider(self) -> None:
        assert CreditExhaustedError("out", provider="zai").provider == "zai"


class TestBackendProbeEndpoint:
    def test_known_backend_resolves_base_url_and_key(self, monkeypatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai-test")
        config = ConfigFactory.create()
        base_url, api_key = backend_probe_endpoint("zai", config)
        assert base_url == config.zai_base_url
        assert api_key == "sk-zai-test"

    def test_anthropic_returns_empty(self) -> None:
        config = ConfigFactory.create()
        assert backend_probe_endpoint("anthropic", config) == ("", "")

    def test_unknown_provider_returns_empty(self) -> None:
        config = ConfigFactory.create()
        assert backend_probe_endpoint("gemini", config) == ("", "")


# ---------------------------------------------------------------------------
# 2. Scoping — _loop_providers / _affected_loops
# ---------------------------------------------------------------------------

_LOOPS = ["triage", "plan", "review", "repo_wiki", "pr_unsticker", "store"]


class TestLoopProviders:
    def test_all_anthropic_by_default(self) -> None:
        orch = HydraFlowOrchestrator(ConfigFactory.create())
        providers = orch._loop_providers(_LOOPS)
        assert set(providers.values()) == {PROVIDER_ANTHROPIC}

    def test_dialed_loop_maps_to_its_backend(self) -> None:
        orch = HydraFlowOrchestrator(
            ConfigFactory.create().model_copy(
                update={"wiki_compilation_provider": "kimi"}
            )
        )
        providers = orch._loop_providers(_LOOPS)
        assert providers["repo_wiki"] == "kimi"
        # A non-dialed loop is unaffected.
        assert providers["plan"] == PROVIDER_ANTHROPIC


class TestAffectedLoops:
    def test_anthropic_cap_spares_backend_routed_loop(self) -> None:
        # THE core #9807 invariant: an Anthropic cap pauses the harness loops but
        # NOT the kimi-routed wiki loop, which keeps ticking.
        orch = HydraFlowOrchestrator(
            ConfigFactory.create().model_copy(
                update={"wiki_compilation_provider": "kimi"}
            )
        )
        affected, terminate = orch._affected_loops("anthropic", _LOOPS, "plan")
        assert "repo_wiki" not in affected
        assert {"triage", "plan", "review", "store"} <= affected
        assert terminate is True  # harness pools are torn down for an Anthropic cap

    def test_backend_cap_scopes_to_that_backend_only(self) -> None:
        orch = HydraFlowOrchestrator(
            ConfigFactory.create().model_copy(
                update={"wiki_compilation_provider": "kimi"}
            )
        )
        affected, terminate = orch._affected_loops("kimi", _LOOPS, "repo_wiki")
        assert affected == {"repo_wiki"}
        assert terminate is False  # harness pools (Anthropic) left running

    def test_backend_cap_always_includes_source(self) -> None:
        # A backend signal raised by a loop the table doesn't map (e.g. a shared
        # sub-step) still pauses+restarts that loop rather than orphaning it.
        orch = HydraFlowOrchestrator(ConfigFactory.create())
        affected, terminate = orch._affected_loops("zai", _LOOPS, "review")
        assert "review" in affected
        assert terminate is False

    def test_unknown_provider_falls_back_to_global(self) -> None:
        orch = HydraFlowOrchestrator(ConfigFactory.create())
        affected, terminate = orch._affected_loops("gemini", _LOOPS, "plan")
        assert affected == set(_LOOPS)
        assert terminate is True


# ---------------------------------------------------------------------------
# 3. Probe-lift per provider
# ---------------------------------------------------------------------------


def _fake_get_client(resp_or_exc):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if isinstance(resp_or_exc, Exception):
        client.get = AsyncMock(side_effect=resp_or_exc)
    else:
        client.get = AsyncMock(return_value=resp_or_exc)
    return client


@pytest.mark.asyncio
class TestPerProviderProbe:
    async def test_anthropic_provider_delegates_to_anthropic_probe(self) -> None:
        # No key configured → Anthropic probe assumes available (fail-open).
        with patch.dict("os.environ", {}, clear=True):
            assert await probe_credit_availability("anthropic") is True

    async def test_backend_200_means_available(self) -> None:
        resp = MagicMock(status_code=200, text="ok")
        with patch("httpx.AsyncClient", return_value=_fake_get_client(resp)):
            result = await probe_credit_availability(
                "zai", base_url="https://api.z.ai", api_key="sk-zai"
            )
        assert result is True

    @pytest.mark.parametrize("code", [402, 429])
    async def test_backend_402_429_means_exhausted(self, code: int) -> None:
        resp = MagicMock(status_code=code, text="insufficient credits")
        with patch("httpx.AsyncClient", return_value=_fake_get_client(resp)):
            result = await probe_credit_availability(
                "kimi", base_url="https://api.moonshot.ai", api_key="sk-kimi"
            )
        assert result is False

    async def test_backend_credit_body_means_exhausted(self) -> None:
        resp = MagicMock(status_code=400, text="your credit balance is too low")
        with patch("httpx.AsyncClient", return_value=_fake_get_client(resp)):
            result = await probe_credit_availability(
                "zai", base_url="https://api.z.ai", api_key="sk-zai"
            )
        assert result is False

    async def test_backend_no_key_fails_open(self) -> None:
        # Cannot probe an unwired backend — assume available so scoping falls
        # back to the text signal rather than masking a real cap.
        result = await probe_credit_availability(
            "zai", base_url="https://x", api_key=""
        )
        assert result is True

    async def test_backend_network_error_fails_open(self) -> None:
        client = _fake_get_client(httpx.ConnectError("boom"))
        with patch("httpx.AsyncClient", return_value=client):
            result = await probe_credit_availability(
                "zai", base_url="https://api.z.ai", api_key="sk-zai"
            )
        assert result is True

    async def test_backend_non_credit_error_fails_open(self) -> None:
        # A 401/404 is auth/routing, not a spent balance — do not pause.
        resp = MagicMock(status_code=404, text="model not found")
        with patch("httpx.AsyncClient", return_value=_fake_get_client(resp)):
            result = await probe_credit_availability(
                "zai", base_url="https://api.z.ai", api_key="sk-zai"
            )
        assert result is True

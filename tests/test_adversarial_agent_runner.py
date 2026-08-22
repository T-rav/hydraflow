"""Tests for the SubprocessAgentRunner adapter.

Covers the AgentLike contract: spawn a one-shot CLI, return raw
stdout, reraise CreditExhaustedError per the dark-factory contract,
and let likely-bug exceptions propagate so they show up in logs.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from adversarial_agent_runner import SubprocessAgentRunner
from config import HydraFlowConfig
from gateway_mint_client import GatewayMintCredential
from subprocess_util import CreditExhaustedError


class FakeRunner:
    """Duck-typed SubprocessRunner that records calls and returns a
    canned ``run_simple`` result.

    Mirrors the pattern used in ``tests/test_term_proposer_runtime.py``.
    """

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        raise_exc: BaseException | None = None,
    ) -> None:
        self._result = subprocess.CompletedProcess(
            args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr
        )
        self._raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def run_simple(
        self,
        cmd,
        *,
        input=None,
        timeout=None,
        env=None,
        cwd=None,  # noqa: A002,
        **_kwargs: object,  # #9577 cancel_check/cancel_poll_interval
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {"cmd": list(cmd), "input": input, "timeout": timeout, "env": env}
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


class TestSubprocessAgentRunnerBasic:
    @pytest.mark.asyncio
    async def test_returns_stdout_as_string(self, config: HydraFlowConfig) -> None:
        runner = FakeRunner(returncode=0, stdout='{"findings": []}')
        agent = SubprocessAgentRunner(runner=runner, config=config)

        out = await agent.run("you are a critic", "review this")

        assert out == '{"findings": []}'

    @pytest.mark.asyncio
    async def test_prompt_concatenates_system_and_user(
        self, config: HydraFlowConfig
    ) -> None:
        runner = FakeRunner(returncode=0, stdout="ok")
        agent = SubprocessAgentRunner(runner=runner, config=config)

        await agent.run("SYS_INSTR", "USR_MSG")

        # The lightweight CLI path passes the prompt either as a CLI
        # argument or via stdin (for >100KB prompts). Our test uses
        # tiny strings → CLI argument. The composed prompt must
        # include both blocks with explicit section headers.
        cmd = runner.calls[0]["cmd"]
        prompt_in_cmd = next(arg for arg in cmd if "SYS_INSTR" in arg)
        assert "SYS_INSTR" in prompt_in_cmd
        assert "USR_MSG" in prompt_in_cmd
        assert "# System instructions" in prompt_in_cmd
        assert "# User message" in prompt_in_cmd

    @pytest.mark.asyncio
    async def test_uses_configured_tool_and_model(
        self, config: HydraFlowConfig
    ) -> None:
        runner = FakeRunner(returncode=0, stdout="ok")
        agent = SubprocessAgentRunner(
            runner=runner,
            config=config,
            tool="claude",
            model="claude-haiku-4-5-test",
        )

        await agent.run("sys", "usr")

        cmd = runner.calls[0]["cmd"]
        assert cmd[0] == "claude"
        assert "claude-haiku-4-5-test" in cmd

    @pytest.mark.asyncio
    async def test_claude_spawn_isolates_user_settings(
        self, config: HydraFlowConfig
    ) -> None:
        # Regression: adversarial judges (SpecJudge, PlanCouncil, …) emit
        # strict JSON. A host user-level superpowers SessionStart hook injects
        # "invoke a skill before responding" guidance that derails the JSON
        # contract (the judge explores the repo instead of voting), so the
        # downstream parser fails with "Expecting value: line 1 column 1".
        # The spawn must restrict settings to the project scope.
        runner = FakeRunner(returncode=0, stdout='{"verdict": "PASS"}')
        agent = SubprocessAgentRunner(runner=runner, config=config, tool="claude")

        await agent.run("sys", "usr")

        cmd = runner.calls[0]["cmd"]
        assert "--setting-sources" in cmd
        assert cmd[cmd.index("--setting-sources") + 1] == "project"


class TestSubprocessAgentRunnerErrorHandling:
    @pytest.mark.asyncio
    async def test_reraises_credit_exhausted_from_stderr(
        self, config: HydraFlowConfig
    ) -> None:
        # Anthropic spend-cap rejection — surfaces in stderr with the
        # canonical pattern matched by ``is_credit_exhaustion``.
        runner = FakeRunner(
            returncode=2,
            stdout="",
            stderr=(
                "Error: Credit balance is too low. "
                "You'll regain access on 2026-06-01 at 00:00 UTC."
            ),
        )
        agent = SubprocessAgentRunner(runner=runner, config=config)

        with pytest.raises(CreditExhaustedError):
            await agent.run("sys", "usr")

    @pytest.mark.asyncio
    async def test_reraises_credit_exhausted_from_stdout(
        self, config: HydraFlowConfig
    ) -> None:
        # Some CLIs print the credit-exhaustion notice on stdout
        # before exiting nonzero.
        runner = FakeRunner(
            returncode=0,
            stdout="Usage limit reached, retry later.",
            stderr="",
        )
        agent = SubprocessAgentRunner(runner=runner, config=config)

        with pytest.raises(CreditExhaustedError):
            await agent.run("sys", "usr")

    @pytest.mark.asyncio
    async def test_likely_bug_exception_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        # reraise_on_credit_or_bug must surface KeyError-class
        # exceptions so we hear about them in logs rather than
        # silently returning an empty soft reply.
        runner = FakeRunner(raise_exc=KeyError("config_missing"))
        agent = SubprocessAgentRunner(runner=runner, config=config)

        with pytest.raises(KeyError):
            await agent.run("sys", "usr")

    @pytest.mark.asyncio
    async def test_transient_oserror_soft_fails_to_empty_string(
        self, config: HydraFlowConfig
    ) -> None:
        # OSError is not in LIKELY_BUG_EXCEPTIONS → swallowed and the
        # adapter returns ""; the caller treats this as "no findings"
        # so a transient subprocess blip doesn't crash the whole
        # adversarial stage.
        runner = FakeRunner(raise_exc=OSError("transient network blip"))
        agent = SubprocessAgentRunner(runner=runner, config=config)

        out = await agent.run("sys", "usr")

        assert out == ""

    @pytest.mark.asyncio
    async def test_nonzero_returncode_without_credit_exhaustion_soft_fails(
        self, config: HydraFlowConfig
    ) -> None:
        # CLI failed for a non-credit reason (parse error, timeout
        # inside the CLI itself, etc.). Soft-fail to "" rather than
        # crashing the host pipeline.
        runner = FakeRunner(returncode=1, stdout="", stderr="unparseable args")
        agent = SubprocessAgentRunner(runner=runner, config=config)

        out = await agent.run("sys", "usr")

        assert out == ""

    @pytest.mark.asyncio
    async def test_timeout_threaded_into_runner(self, config: HydraFlowConfig) -> None:
        runner = FakeRunner(returncode=0, stdout="ok")
        agent = SubprocessAgentRunner(runner=runner, config=config, timeout=42.0)

        await agent.run("sys", "usr")

        assert runner.calls[0]["timeout"] == 42.0


class _FakeGatewayClient:
    async def mint_key(self, **_kwargs: object) -> GatewayMintCredential:
        return GatewayMintCredential(
            key_id="adversarial-key",
            token="hfgw_adversarial_virtual",
            expires_at="2099-08-19T12:05:00Z",
        )

    async def revoke_key(self, **_kwargs: object) -> bool:
        return True


@pytest.mark.asyncio
async def test_fleet_ratchet_routes_adversarial_spawn_through_virtual_env(
    config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The formerly-grandfathered critic cannot retain a real provider key."""
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-anthropic-secret")
    monkeypatch.setenv("ZAI_API_KEY", "real-zai-secret")
    object.__setattr__(config, "gateway_fleet_ratchet_enabled", True)
    object.__setattr__(config, "gateway_base_url", "http://gateway:8080")
    runner = FakeRunner(returncode=0, stdout='{"verdict": "PASS"}')
    agent = SubprocessAgentRunner(
        runner=runner,
        config=config,
        tool="claude",
        model="sonnet",
        provider="claude",
    )

    with patch(
        "runner_utils._HttpGatewayControlClient", return_value=_FakeGatewayClient()
    ):
        await agent.run("sys", "usr")

    env = runner.calls[0]["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://gateway:8080"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "hfgw_adversarial_virtual"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert "ZAI_API_KEY" not in env
    assert "HYDRAFLOW_GATEWAY_CONTROL_TOKEN" not in env
    assert "real-anthropic-secret" not in env.values()
    assert "real-zai-secret" not in env.values()

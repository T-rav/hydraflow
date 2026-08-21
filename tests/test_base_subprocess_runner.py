"""BaseSubprocessRunner unit tests (spec §3.1).

Mocks `stream_claude_process` at the module boundary so no real Claude
Code subprocess is spawned. Verifies:

- subclass abstract methods are required (TypeError on instantiation).
- happy path: outcome.transcript, usage_stats, prompt_hash flow through.
- auth-retry loop: transient AuthenticationRetryError retries up to
  _AUTH_RETRY_MAX times; auth-retry exhausted → crashed=True.
- credit / terminal-auth errors propagate (loop can suspend).
- generic exceptions collapse to crashed=True (never-raises contract).
- telemetry write failure is logged but doesn't fail the run.
- cost estimate default works against the model_pricing table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
    _coerce_int,
)
from tests.helpers import ConfigFactory


@dataclass(frozen=True)
class _FakeResult:
    """Test-only result type satisfying the T_Result contract."""

    crashed: bool
    transcript: str
    cost_usd: float
    tokens: int
    prompt_hash: str


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    """Concrete subclass for tests."""

    def _telemetry_source(self) -> str:
        return "fake_runner_test"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["fake-claude", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        return _FakeResult(
            crashed=outcome.crashed,
            transcript=outcome.transcript,
            cost_usd=outcome.cost_usd,
            tokens=_coerce_int(outcome.usage_stats.get("total_tokens")),
            prompt_hash=outcome.prompt_hash,
        )


def _make_runner(**config_overrides: Any) -> _FakeRunner:
    config = ConfigFactory.create(**config_overrides)
    bus = MagicMock()
    bus.current_session_id = "test-session"
    return _FakeRunner(config=config, event_bus=bus)


def test_abstract_methods_required() -> None:
    """BaseSubprocessRunner cannot be instantiated without subclass overrides."""
    config = ConfigFactory.create()
    bus = MagicMock()
    with pytest.raises(TypeError):
        BaseSubprocessRunner(config=config, event_bus=bus)  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_happy_path_yields_outcome(tmp_path: Path) -> None:
    async def fake_stream(*, config, **kwargs: Any) -> str:
        config.usage_stats["input_tokens"] = 100
        config.usage_stats["output_tokens"] = 50
        config.usage_stats["total_tokens"] = 150
        return "<status>resolved</status>"

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ):
        result = await runner.run(
            prompt="hello", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is False
    assert "resolved" in result.transcript
    assert result.tokens == 150
    assert result.prompt_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_gateway_routed_spawn_marks_prompt_telemetry_transport(
    tmp_path: Path,
) -> None:
    class _GatewayRunner(_FakeRunner):
        def _build_command(self, prompt: str, worktree: Path) -> list[str]:
            return ["claude", "--model", self._config.model, "-p"]

    config = ConfigFactory.create()
    object.__setattr__(config, "gateway_fleet_ratchet_enabled", True)
    bus = MagicMock()
    bus.current_session_id = "gateway-session"
    runner = _GatewayRunner(config=config, event_bus=bus)
    isolated_runner = AsyncMock()

    with (
        patch(
            "runners.base_subprocess_runner.resolve_harness_env",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            new_callable=AsyncMock,
            return_value="complete",
        ) as stream_mock,
        patch(
            "runners.base_subprocess_runner._terminal_gateway_runner",
            return_value=(isolated_runner, isolated_runner),
        ),
        patch(
            "runners.base_subprocess_runner.revoke_gateway_key",
            new_callable=AsyncMock,
        ),
    ):
        result = await runner.run(
            prompt="gateway prompt",
            worktree_path=str(tmp_path),
            issue_number=1,
        )

    rows = [
        json.loads(line)
        for line in config.cost_inferences_path.read_text().splitlines()
        if line
    ]
    assert result.crashed is False
    assert rows[-1]["tool"] == "gateway"
    assert rows[-1]["model"] == config.model
    assert stream_mock.await_args.kwargs["config"].runner is isolated_runner
    isolated_runner.cleanup.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_auth_retry_then_success(tmp_path: Path) -> None:
    """Two transient AuthenticationRetryErrors retry; third call succeeds."""
    from runner_utils import AuthenticationRetryError

    call_count = 0

    async def fake_stream(**kwargs: Any) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise AuthenticationRetryError("transient OAuth")
        return "<status>resolved</status>"

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=fake_stream,
        ),
        patch(
            "runners.base_subprocess_runner.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "runners.base_subprocess_runner.renew_gateway_key_if_needed",
            new_callable=AsyncMock,
            return_value=False,
        ) as renew_mock,
        patch(
            "runners.base_subprocess_runner.revoke_gateway_key",
            new_callable=AsyncMock,
        ) as revoke_mock,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert call_count == 3
    assert result.crashed is False
    assert renew_mock.await_count == 2
    assert revoke_mock.await_count == 1


@pytest.mark.asyncio
async def test_auth_retry_exhausted_marks_crashed(tmp_path: Path) -> None:
    from runner_utils import AuthenticationRetryError

    async def always_auth_fail(**kwargs: Any) -> str:
        raise AuthenticationRetryError("OAuth refresh broken")

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=always_auth_fail,
        ),
        patch("runners.base_subprocess_runner.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is True
    assert "auth retry exhausted" in result.transcript


@pytest.mark.asyncio
async def test_credit_exhausted_propagates(tmp_path: Path) -> None:
    """CreditExhaustedError must propagate so the caretaker loop suspends."""
    from subprocess_util import CreditExhaustedError

    async def credit_exhausted(**kwargs: Any) -> str:
        raise CreditExhaustedError("api credits at zero")

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=credit_exhausted,
        ),
        pytest.raises(CreditExhaustedError),
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)


@pytest.mark.asyncio
async def test_generic_exception_collapses_to_crashed(tmp_path: Path) -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("subprocess oom")

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process", side_effect=boom
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is True
    assert "spawn error" in result.transcript


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_fail_run(tmp_path: Path) -> None:
    async def stream_ok(**kwargs: Any) -> str:
        return "<status>needs_human</status>"

    runner = _make_runner()
    runner._telemetry = MagicMock()
    runner._telemetry.record = MagicMock(side_effect=OSError("disk full"))
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_ok,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is False  # run succeeded despite telemetry failure


@pytest.mark.asyncio
async def test_cost_estimate_default_returns_non_negative(tmp_path: Path) -> None:
    async def fake_stream(*, config, **kwargs: Any) -> str:
        config.usage_stats["input_tokens"] = 100
        config.usage_stats["output_tokens"] = 50
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.cost_usd >= 0.0


@pytest.mark.asyncio
async def test_pre_spawn_hook_is_called(tmp_path: Path) -> None:
    """Subclass override of _pre_spawn_hook fires once before stream_claude_process."""
    pre_calls: list[str] = []

    class _HookRunner(_FakeRunner):
        def _pre_spawn_hook(self, prompt: str) -> None:
            pre_calls.append(prompt)

    config = ConfigFactory.create()
    bus = MagicMock()
    bus.current_session_id = "test-session"
    runner = _HookRunner(config=config, event_bus=bus)

    async def stream_ok(**kwargs: Any) -> str:
        return ""

    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_ok,
    ):
        await runner.run(prompt="hi", worktree_path=str(tmp_path), issue_number=1)
    assert pre_calls == ["hi"]


@pytest.mark.asyncio
async def test_run_threads_issue_number_into_harness_env(tmp_path: Path) -> None:
    """The gateway mint attributes spend to the issue this spawn works on."""
    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.resolve_harness_env",
            new_callable=AsyncMock,
            return_value={},
        ) as resolve_mock,
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            new_callable=AsyncMock,
            return_value="<status>resolved</status>",
        ),
    ):
        await runner.run(
            prompt="hello", worktree_path=str(tmp_path), issue_number=11464
        )

    assert resolve_mock.await_args.kwargs["issue_number"] == 11464

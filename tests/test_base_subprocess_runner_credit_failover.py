"""BaseSubprocessRunner reroutes to GLM under credit-failover (#10844).

auto_agent_preflight (the sole BaseSubprocessRunner consumer) always spawns on
native Claude. Without this wiring, a Claude cap would crash-loop the loop
instead of failing over — the reviewer's Issue 2. This asserts the reroute.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import credit_failover
from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome
from tests.helpers import ConfigFactory

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _FakeResult:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    def _telemetry_source(self) -> str:
        return "fake_runner_failover_test"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["fake-claude", "--model", "claude-opus-4-8", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        return _FakeResult(crashed=outcome.crashed, transcript=outcome.transcript)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _make_runner() -> _FakeRunner:
    bus = MagicMock()
    bus.current_session_id = "test-session"
    return _FakeRunner(config=ConfigFactory.create(), event_bus=bus)


async def _capture(runner: _FakeRunner, tmp_path: Path) -> dict:
    captured: dict = {}

    async def fake_stream(*, config: Any, **kwargs: Any) -> str:
        captured["provider"] = config.provider
        captured["cmd"] = kwargs["cmd"]
        return "<status>resolved</status>"

    with patch(
        "runners.base_subprocess_runner.stream_claude_process", side_effect=fake_stream
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)
    return captured


@pytest.mark.asyncio
async def test_stays_on_claude_when_failover_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    captured = await _capture(_make_runner(), tmp_path)
    assert captured["provider"] == "claude"
    assert "glm-5.2" not in captured["cmd"]


@pytest.mark.asyncio
async def test_reroutes_to_glm_when_failover_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    captured = await _capture(_make_runner(), tmp_path)
    assert captured["provider"] == "zai"
    assert "glm-5.2" in captured["cmd"]
    assert "claude-opus-4-8" not in captured["cmd"]

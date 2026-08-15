"""BaseSubprocessRunner reroutes to GLM via the repo-wide dial (#11211).

Mirrors test_base_subprocess_runner_credit_failover.py: auto_agent_preflight
(the sole BaseSubprocessRunner consumer today) has no PROVIDER_FIELD dial of
its own — it always spawns on native Claude — so the repo-wide repo_provider
override is the only lever for routing this seam's spawns to GLM (issue
#11211 Direction item 2: "the second spawn seam per ADR-0119").
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import credit_failover
from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome
from tests.helpers import ConfigFactory


class _FakeResult:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    def _telemetry_source(self) -> str:
        return "fake_runner_repo_provider_test"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["fake-claude", "--model", "claude-opus-4-8", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        return _FakeResult(crashed=outcome.crashed, transcript=outcome.transcript)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _make_runner(**cfg_overrides: Any) -> _FakeRunner:
    bus = MagicMock()
    bus.current_session_id = "test-session"
    return _FakeRunner(config=ConfigFactory.create(**cfg_overrides), event_bus=bus)


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
async def test_stays_on_claude_when_repo_provider_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    captured = await _capture(_make_runner(), tmp_path)
    assert captured["provider"] == "claude"
    assert "glm-5.2" not in captured["cmd"]


@pytest.mark.asyncio
async def test_reroutes_to_zai_when_repo_provider_is_zai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    runner = _make_runner(repo_provider="zai", repo_model="glm-5.2")
    captured = await _capture(runner, tmp_path)
    assert captured["provider"] == "zai"
    assert "glm-5.2" in captured["cmd"]
    assert "claude-opus-4-8" not in captured["cmd"]


@pytest.mark.asyncio
async def test_no_reroute_without_zai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
    runner = _make_runner(repo_provider="zai", repo_model="glm-5.2")
    captured = await _capture(runner, tmp_path)
    assert captured["provider"] == "claude"

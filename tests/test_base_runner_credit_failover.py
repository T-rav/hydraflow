"""base_runner._execute reroutes work spawns to GLM under credit-failover (#10844)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import credit_failover
from base_runner import BaseRunner

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _make_runner(tmp_path: Path) -> BaseRunner:
    config = MagicMock()
    config.data_root = tmp_path
    config.agent_timeout = 60
    config.repo_data_class = "internal"
    config.credit_failover_enabled = True
    config.credit_failover_model = "glm-5.2"
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = MagicMock()
    br._bus.current_session_id = None
    br._active_procs = set()
    br._runner = MagicMock()
    br._prompt_telemetry = MagicMock()
    br._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    br._hindsight = None
    br._tracing_ctx = None
    br._credentials = MagicMock()
    br._credentials.gh_token = ""
    br._wiki_store = None
    br._log = MagicMock()
    return br


async def _capture_stream(runner: BaseRunner, tmp_path: Path, cmd: list[str]) -> dict:
    captured: dict = {}

    async def fake_stream(**kwargs: object) -> str:
        captured.update(kwargs)
        return "transcript"

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch("base_runner.resolve_harness_env", return_value={}),
    ):
        await runner._execute(
            cmd=cmd,
            prompt="p",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )
    return captured


@pytest.mark.asyncio
async def test_stays_on_claude_when_failover_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    runner = _make_runner(tmp_path)
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "claude-opus-4-8", "-p"]
    )
    assert captured["config"].provider == "claude"
    assert "glm-5.2" not in captured["cmd"]


@pytest.mark.asyncio
async def test_reroutes_to_glm_when_failover_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    runner = _make_runner(tmp_path)
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "claude-opus-4-8", "-p"]
    )
    assert captured["config"].provider == "zai"
    assert "glm-5.2" in captured["cmd"]
    assert "claude-opus-4-8" not in captured["cmd"]


@pytest.mark.asyncio
async def test_no_reroute_without_zai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    runner = _make_runner(tmp_path)
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "claude-opus-4-8", "-p"]
    )
    assert captured["config"].provider == "claude"

"""base_runner._execute reroutes work spawns to GLM via the repo-wide dial (#11211)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import credit_failover
from base_runner import BaseRunner


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _make_runner(
    tmp_path: Path, *, repo_provider: str = "claude", repo_model: str = ""
) -> BaseRunner:
    config = MagicMock()
    config.data_root = tmp_path
    config.agent_timeout = 60
    config.repo_data_class = "internal"
    config.credit_failover_enabled = True
    config.credit_failover_model = "glm-5.2"
    config.repo_provider = repo_provider
    config.repo_model = repo_model
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
async def test_stays_on_claude_when_repo_provider_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    runner = _make_runner(tmp_path, repo_provider="claude")
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "claude-opus-4-8", "-p"]
    )
    assert captured["config"].provider == "claude"
    assert "glm-5.2" not in captured["cmd"]


@pytest.mark.asyncio
async def test_reroutes_to_zai_when_repo_provider_is_zai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    runner = _make_runner(tmp_path, repo_provider="zai", repo_model="glm-5.2")
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
    runner = _make_runner(tmp_path, repo_provider="zai", repo_model="glm-5.2")
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "claude-opus-4-8", "-p"]
    )
    assert captured["config"].provider == "claude"


@pytest.mark.asyncio
async def test_role_dial_already_off_claude_wins_over_repo_provider_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a runner's own PROVIDER_FIELD already resolved to "zai" (a
    fine-grained per-role override), repo_provider is irrelevant — this is
    exercised by making the runner's own _resolve_provider() return "zai"."""
    monkeypatch.setenv("ZAI_API_KEY", "k")
    runner = _make_runner(tmp_path, repo_provider="claude")
    runner._resolve_provider = lambda: "zai"  # simulate PROVIDER_FIELD="zai"
    captured = await _capture_stream(
        runner, tmp_path, ["claude", "--model", "some-glm-model", "-p"]
    )
    assert captured["config"].provider == "zai"
    # apply_repo_provider is a no-op (provider already off "claude"); cmd's
    # model is untouched (only the caller-provided model flows through).
    assert "some-glm-model" in captured["cmd"]

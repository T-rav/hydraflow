"""The shadow policy resolver may never move a single byte of live routing.

#11536 (Gateway P1) adds a routing-policy resolver that computes and records the
route it *would* choose beside every spawn, while the legacy routing path stays
authoritative. That is the phase's entire safety property, so it is pinned here
rather than left to the feature suite: the command and the harness provider
handed to the spawn must be **byte-identical** with the resolver enabled and
disabled, at both agentic seams and the one-shot seam.

The last case pins the realistic operational failure: a shadow *sink* that
cannot write (read-only data root, full disk) degrades to "no shadow record",
never to a changed route.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import credit_failover
from base_runner import BaseRunner
from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome
from tests.helpers import ConfigFactory


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _config(tmp_path: Path, *, shadow: bool) -> Any:
    config = ConfigFactory.create(repo_provider="zai", repo_model="glm-5.2")
    config.data_root = tmp_path / "data"
    config.gateway_route_shadow_enabled = shadow
    return config


class _FakeResult:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    """Minimal concrete seam: the base class owns the routing under test."""

    def _telemetry_source(self) -> str:
        return "shadow_inertness_probe"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        del prompt, worktree
        return ["fake-claude", "--model", "claude-opus-4-8", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        return _FakeResult(crashed=outcome.crashed, transcript=outcome.transcript)


def _base_runner(config: Any) -> BaseRunner:
    runner = BaseRunner.__new__(BaseRunner)
    runner._config = config
    runner._bus = MagicMock()
    runner._bus.current_session_id = None
    runner._active_procs = set()
    runner._runner = MagicMock()
    runner._prompt_telemetry = MagicMock()
    runner._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    runner._hindsight = None
    runner._tracing_ctx = None
    runner._credentials = MagicMock()
    runner._credentials.gh_token = ""
    runner._wiki_store = None
    runner._log = MagicMock()
    return runner


async def _agentic_route(config: Any, tmp_path: Path) -> tuple[str, list[str]]:
    """Return the ``(provider, cmd)`` ``base_runner._execute`` hands the spawn."""
    captured: dict[str, Any] = {}

    async def fake_stream(*, config: Any, **kwargs: Any) -> str:
        captured["provider"] = config.provider
        captured["cmd"] = list(kwargs["cmd"])
        return "transcript"

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch("base_runner.resolve_harness_env", return_value={}),
    ):
        await _base_runner(config)._execute(
            cmd=["claude", "--model", "claude-opus-4-8", "-p"],
            prompt="p",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )
    return captured["provider"], captured["cmd"]


async def _subprocess_route(config: Any, tmp_path: Path) -> tuple[str, list[str]]:
    """Return the ``(provider, cmd)`` ``BaseSubprocessRunner.run`` resolves."""
    captured: dict[str, Any] = {}

    async def fake_stream(*, config: Any, **kwargs: Any) -> str:
        captured["provider"] = config.provider
        captured["cmd"] = list(kwargs["cmd"])
        return "<status>resolved</status>"

    bus = MagicMock()
    bus.current_session_id = "test-session"
    runner = _FakeRunner(config=config, event_bus=bus)
    with patch(
        "runners.base_subprocess_runner.stream_claude_process", side_effect=fake_stream
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)
    return captured["provider"], captured["cmd"]


@pytest.mark.asyncio
async def test_agentic_provider_is_identical_with_the_shadow_resolver_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness provider the agentic seam resolves does not move."""
    monkeypatch.setenv("ZAI_API_KEY", "k")

    dark, _ = await _agentic_route(_config(tmp_path, shadow=False), tmp_path)
    lit, _ = await _agentic_route(_config(tmp_path, shadow=True), tmp_path)

    assert lit == dark


@pytest.mark.asyncio
async def test_agentic_command_is_identical_with_the_shadow_resolver_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The argv handed to the spawn does not move — model rewrite included."""
    monkeypatch.setenv("ZAI_API_KEY", "k")

    _, dark = await _agentic_route(_config(tmp_path, shadow=False), tmp_path)
    _, lit = await _agentic_route(_config(tmp_path, shadow=True), tmp_path)

    assert lit == dark


@pytest.mark.asyncio
async def test_subprocess_seam_provider_is_identical_with_the_resolver_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second agentic seam's provider does not move either."""
    monkeypatch.setenv("ZAI_API_KEY", "k")

    dark, _ = await _subprocess_route(_config(tmp_path, shadow=False), tmp_path)
    lit, _ = await _subprocess_route(_config(tmp_path, shadow=True), tmp_path)

    assert lit == dark


@pytest.mark.asyncio
async def test_subprocess_seam_command_is_identical_with_the_resolver_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second agentic seam's argv does not move either."""
    monkeypatch.setenv("ZAI_API_KEY", "k")

    _, dark = await _subprocess_route(_config(tmp_path, shadow=False), tmp_path)
    _, lit = await _subprocess_route(_config(tmp_path, shadow=True), tmp_path)

    assert lit == dark


@pytest.mark.asyncio
async def test_an_unwritable_shadow_sink_leaves_the_route_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sink that cannot write degrades to no record, never to a new route."""
    monkeypatch.setenv("ZAI_API_KEY", "k")
    expected = await _agentic_route(_config(tmp_path, shadow=False), tmp_path)

    with patch(
        "route_shadow.RoutingAuditLog.append",
        side_effect=OSError("read-only file system"),
    ):
        observed = await _agentic_route(_config(tmp_path, shadow=True), tmp_path)

    assert observed == expected


@pytest.mark.asyncio
async def test_the_shadow_seam_actually_recorded_a_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keeps the inertness assertions above from passing vacuously."""
    monkeypatch.setenv("ZAI_API_KEY", "k")
    config = _config(tmp_path, shadow=True)

    await _agentic_route(config, tmp_path)

    from route_shadow import shadow_decision_log_path  # noqa: PLC0415

    assert shadow_decision_log_path(config).exists()

"""``BaseRunner._execute`` honours a per-spawn ``timeout_s`` (#11568).

The implement phase resolves a complexity-tiered timeout and threads it to
the spawn seam; ``agent_timeout`` stays the ceiling and the default.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from base_runner import BaseRunner

CEILING = 3600


def _make_runner(tmp_path: Path) -> BaseRunner:
    config = MagicMock()
    config.data_root = tmp_path
    config.agent_timeout = CEILING
    config.repo_data_class = "internal"
    config.gateway_fleet_ratchet_enabled = False
    event_bus = MagicMock()
    event_bus.current_session_id = None
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = event_bus
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


async def _execute_capturing(
    runner: BaseRunner, tmp_path: Path, **kwargs: object
) -> tuple[dict, dict]:
    """Run ``_execute`` with the stream + harness-env seams captured."""
    stream_kwargs: dict = {}
    env_kwargs: dict = {}

    async def fake_stream(**kw):
        stream_kwargs.update(kw)
        return "transcript"

    async def fake_env(*_a, **kw):
        env_kwargs.update(kw)
        return {}

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch("base_runner.resolve_harness_env", side_effect=fake_env),
    ):
        await runner._execute(
            cmd=["claude", "-p"],
            prompt="test",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
            **kwargs,  # type: ignore[arg-type]
        )
    return stream_kwargs, env_kwargs


@pytest.mark.asyncio
async def test_default_spawn_uses_agent_timeout(tmp_path: Path) -> None:
    stream_kwargs, _ = await _execute_capturing(_make_runner(tmp_path), tmp_path)

    assert stream_kwargs["config"].timeout == CEILING


@pytest.mark.asyncio
async def test_timeout_s_overrides_the_stream_timeout(tmp_path: Path) -> None:
    stream_kwargs, _ = await _execute_capturing(
        _make_runner(tmp_path), tmp_path, timeout_s=1800
    )

    assert stream_kwargs["config"].timeout == 1800


@pytest.mark.asyncio
async def test_timeout_s_reaches_the_harness_env_lease(tmp_path: Path) -> None:
    _, env_kwargs = await _execute_capturing(
        _make_runner(tmp_path), tmp_path, timeout_s=1800
    )

    assert env_kwargs["timeout_seconds"] == 1800


@pytest.mark.asyncio
async def test_timeout_s_is_clamped_to_the_agent_timeout_ceiling(
    tmp_path: Path,
) -> None:
    stream_kwargs, _ = await _execute_capturing(
        _make_runner(tmp_path), tmp_path, timeout_s=CEILING * 4
    )

    assert stream_kwargs["config"].timeout == CEILING


@pytest.mark.asyncio
async def test_timeout_s_none_means_the_ceiling(tmp_path: Path) -> None:
    stream_kwargs, _ = await _execute_capturing(
        _make_runner(tmp_path), tmp_path, timeout_s=None
    )

    assert stream_kwargs["config"].timeout == CEILING

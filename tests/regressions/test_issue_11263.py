"""Regression pins for #11263 — docker spawns dropped the harness override.

Credit-failover (#10844) and repo-provider routing (#11211) rewrite a
spawn's ``--model`` to glm and rely on ``resolve_harness_env`` to point the
Claude CLI at z.ai's Anthropic-compatible endpoint. The override travelled
inside the ``env=`` dict — which ``DockerRunner.create_streaming_process``
IGNORES by design (container isolation) — so every docker-executed rerouted
spawn hit the native Anthropic endpoint with a glm model and died with
``[claude-code:unrecognized_model]`` exit 1 (live evidence 2026-08-15
13:24Z/14:52Z; failover was only effective on host-executed seams).

The override now travels as its own ``harness_env`` parameter that every
runner MUST honor: docker merges it after ``_build_env`` (it is a bounded
three-key allowlist, not a host-env leak), host merges it into the spawn
env, and ``stream_claude_process`` threads ``StreamConfig.harness_env``
through unconditionally.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from runner_utils import StreamConfig, stream_claude_process

_LOG = logging.getLogger("test.issue11263")

_HARNESS = {
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "zai-token",
    "ANTHROPIC_API_KEY": "",
}


class _RecordingRunner:
    """Captures the kwargs the stream seam passes to the runner."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_streaming_process(self, cmd: Any, **kwargs: Any) -> Any:
        self.calls.append({"cmd": list(cmd), **kwargs})
        return await asyncio.create_subprocess_exec(
            "true",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def run_simple(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def cleanup(self) -> None:  # pragma: no cover
        return None


async def test_stream_seam_passes_harness_env_as_its_own_param(tmp_path) -> None:
    runner = _RecordingRunner()
    await stream_claude_process(
        cmd=["claude", "-p", "--model", "glm-5.2"],
        prompt="hi",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=None,
        event_data={},
        logger=_LOG,
        config=StreamConfig(runner=runner, harness_env=dict(_HARNESS), timeout=10),
    )
    assert runner.calls, "runner was never invoked"
    call = runner.calls[0]
    assert call.get("harness_env") == _HARNESS, (
        "harness_env must reach the runner as its OWN kwarg — inside env= it "
        "is silently dropped by DockerRunner (#11263)"
    )


async def test_host_runner_merges_harness_env_over_env(monkeypatch) -> None:
    from execution import HostRunner

    captured: dict[str, Any] = {}
    real_exec = asyncio.create_subprocess_exec

    async def _capture(*cmd: str, **kwargs: Any):
        captured.update(kwargs)
        return await real_exec(
            "true",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _capture)
    await HostRunner().create_streaming_process(
        ["claude", "-p"],
        env={"ANTHROPIC_API_KEY": "sk-native", "PATH": "/usr/bin"},
        harness_env=dict(_HARNESS),
    )
    env = captured["env"]
    assert env["ANTHROPIC_BASE_URL"] == _HARNESS["ANTHROPIC_BASE_URL"]
    assert env["ANTHROPIC_API_KEY"] == ""  # override wins over the native key
    assert env["PATH"] == "/usr/bin"  # base env preserved


async def test_mockworld_fake_records_harness_env() -> None:
    """The air-gapped fake must record the override so scenarios can assert
    backend routing without spawning (review find: recording was inert)."""
    from mockworld.fakes.fake_docker import FakeDocker
    from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner

    docker = FakeDocker()
    docker.script_run([])  # one scripted empty run for the fake spawn
    fake = FakeSubprocessRunner(docker=docker)
    await fake.create_streaming_process(["claude", "-p"], harness_env=dict(_HARNESS))
    assert fake.last_harness_env == _HARNESS

"""``AgentRunner.run`` forwards the tiered ``timeout_s`` to ``_execute`` (#11568)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent import AgentRunner
from events import EventBus
from models import LoopResult
from tests.conftest import TaskFactory


def _patched(runner: AgentRunner):
    return (
        patch.object(
            runner, "_execute", new_callable=AsyncMock, return_value="transcript"
        ),
        patch.object(
            runner,
            "_verify_result",
            new_callable=AsyncMock,
            return_value=LoopResult(passed=True, summary="OK"),
        ),
        patch.object(runner, "_count_commits", new_callable=AsyncMock, return_value=1),
        patch.object(runner, "_save_transcript"),
    )


@pytest.mark.asyncio
async def test_run_forwards_timeout_s_to_execute(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    runner = AgentRunner(config, event_bus)
    exec_patch, verify_patch, count_patch, save_patch = _patched(runner)

    with exec_patch as mock_exec, verify_patch, count_patch, save_patch:
        await runner.run(
            TaskFactory.create(), tmp_path, "agent/issue-42", timeout_s=1800
        )

    # The main build is the first spawn; pre-quality review spawns follow it.
    assert mock_exec.await_args_list[0].kwargs["timeout_s"] == 1800


@pytest.mark.asyncio
async def test_run_without_timeout_s_forwards_none(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    """No tier known → ``None`` → ``_execute`` falls back to ``agent_timeout``."""
    runner = AgentRunner(config, event_bus)
    exec_patch, verify_patch, count_patch, save_patch = _patched(runner)

    with exec_patch as mock_exec, verify_patch, count_patch, save_patch:
        await runner.run(TaskFactory.create(), tmp_path, "agent/issue-42")

    assert mock_exec.await_args_list[0].kwargs["timeout_s"] is None

"""AgentTraceBuilder unit tests — scripts LLM runner results."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.trace import AgentTraceBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


def test_happy_path_preset_scripts_success_result(world: MockWorld) -> None:
    AgentTraceBuilder().happy_path().for_phase("implement").for_issue(1).at(world)
    # FakeLLM should now yield success for issue 1's implement phase
    scripted = world._llm.agents._scripts.get(1)
    assert scripted is not None and len(scripted) == 1
    assert getattr(scripted[0], "success", False) is True


def test_script_sequence_yields_each_result_in_order(world: MockWorld) -> None:
    AgentTraceBuilder().fail_then_succeed().for_phase("plan").for_issue(2).at(world)
    scripts = world._llm.planners._scripts.get(2)
    assert scripts is not None and len(scripts) == 2
    assert getattr(scripts[0], "success", True) is False
    assert getattr(scripts[1], "success", False) is True


def test_phase_required_before_at(world: MockWorld) -> None:
    with pytest.raises(ValueError, match="for_phase"):
        AgentTraceBuilder().happy_path().for_issue(3).at(world)

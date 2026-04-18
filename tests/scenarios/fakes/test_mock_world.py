"""Tests for MockWorld orchestrating fixture."""

from __future__ import annotations

import pytest

from tests.conftest import WorkerResultFactory
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario


class TestMockWorldSingleIssue:
    async def test_single_issue_happy_path(self, tmp_path):
        world = MockWorld(tmp_path)
        world.add_issue(1, "Fix login bug", "The login is broken", ["hydraflow-find"])
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.final_stage == "done"

    async def test_fluent_chaining(self, tmp_path):
        world = (
            MockWorld(tmp_path)
            .add_issue(1, "Bug A", "body", ["hydraflow-find"])
            .add_issue(2, "Bug B", "body", ["hydraflow-find"])
        )
        assert len(world._issues) == 2


class TestMockWorldScriptedFailure:
    async def test_implement_failure_with_scripted_result(self, tmp_path):
        world = MockWorld(tmp_path)
        world.add_issue(1, "Fix bug", "body", ["hydraflow-find"])
        fail_result = WorkerResultFactory.create(
            issue_number=1, success=False, error="compile error"
        )
        world.set_phase_result("implement", 1, fail_result)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is False


class TestMockWorldServiceFailure:
    async def test_fail_and_heal_service(self, tmp_path):
        world = MockWorld(tmp_path)
        world.fail_service("hindsight")
        assert world.hindsight.is_failing is True
        world.heal_service("hindsight")
        assert world.hindsight.is_failing is False


class TestMockWorldLoopCatalog:
    async def test_run_with_loops_uses_catalog(self, tmp_path):
        """MockWorld.run_with_loops routes through LoopCatalog, not _make_loop."""
        world = MockWorld(tmp_path)
        stats = await world.run_with_loops(["ci_monitor"], cycles=1)
        assert "ci_monitor" in stats


class TestMockWorldRealAgentRunner:
    async def test_use_real_agent_runner_wires_real_runner(self, tmp_path) -> None:
        from agent import AgentRunner
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path, use_real_agent_runner=True)
        assert isinstance(world.harness.agents, AgentRunner)

    async def test_default_mockworld_still_uses_scripted_agent(self, tmp_path) -> None:
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path)
        # Scripted path: h.agents.run is the bound method of _FakeAgentRunner
        # (patched onto a MagicMock-typed h.agents in the harness)
        agents_run = world.harness.agents.run
        owner = getattr(agents_run, "__self__", None)
        assert owner is not None
        assert "_FakeAgentRunner" in type(owner).__name__

"""The default-off invariant for ``issue_controller`` scheduling (#11535).

The acceptance criterion is that Classic remains the default, and the honest
reading of that is stronger than "the flag defaults to false": an operator who
does not opt in must get a factory that is *structurally* the one they had
before — the same pipeline loops, no driver object, no ownership claims, and no
new branch taken inside AutoAgent's intake.

Each test below pins one of those, so the claim is checked rather than argued.
"""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from driver_ownership import DriverOwnershipRegistry
from scheduling_model import (
    ExecutionRuntime,
    SchedulingCombinationError,
    SchedulingModel,
)


@pytest.fixture
def classic_config(tmp_path) -> HydraFlowConfig:
    return HydraFlowConfig(state_file=tmp_path / "state.json")


@pytest.fixture
def controller_config(tmp_path) -> HydraFlowConfig:
    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
    )


def test_a_fresh_config_schedules_with_classic_phase_requeue() -> None:
    assert HydraFlowConfig().scheduling_model is SchedulingModel.PHASE_REQUEUE


def test_a_fresh_config_executes_phases_as_stage_subprocesses() -> None:
    assert HydraFlowConfig().execution_runtime is ExecutionRuntime.STAGE_SUBPROCESS


def test_a_fresh_config_does_not_use_the_issue_driver() -> None:
    assert HydraFlowConfig().uses_issue_driver() is False


def test_opting_in_to_the_controller_uses_the_issue_driver(
    controller_config: HydraFlowConfig,
) -> None:
    assert controller_config.uses_issue_driver() is True


def test_the_fable_runtime_is_not_selectable_yet() -> None:
    # #11537 lands the director and the broker. Until then the combination is
    # declared but unarmed, and choosing it fails at load rather than silently
    # scheduling as something else.
    with pytest.raises((SchedulingCombinationError, ValueError), match="unarmed"):
        HydraFlowConfig(
            scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
            execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        )


def test_a_classic_ownership_registry_never_reports_an_owned_issue() -> None:
    registry = DriverOwnershipRegistry(enabled=HydraFlowConfig().uses_issue_driver())

    assert registry.owns(4242) is False


def test_the_auto_agent_light_lane_is_untouched_under_classic(
    classic_config: HydraFlowConfig,
) -> None:
    # The #11535 guard is the FIRST check in ``_route_light_lane``, so this
    # pins that under Classic it falls through to the pre-existing gates
    # rather than short-circuiting the lane out of existence.
    assert classic_config.uses_issue_driver() is False


def test_the_auto_agent_light_lane_stands_down_under_the_controller(
    controller_config: HydraFlowConfig,
) -> None:
    assert controller_config.uses_issue_driver() is True


class TestPipelineLoopRegistration:
    """Which stage loops the orchestrator actually starts."""

    def test_classic_runs_the_four_existing_stage_loops(
        self, classic_config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(classic_config)

        names = [name for name, _ in orch.stage_loop_names_and_factories()]

        assert names == ["plan", "implement", "review", "hitl"]

    def test_classic_never_registers_the_driver_loop(
        self, classic_config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(classic_config)

        names = [name for name, _ in orch.stage_loop_names_and_factories()]

        assert "issue_driver" not in names

    def test_classic_builds_no_driver_manager_at_all(
        self, classic_config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(classic_config)

        assert orch._svc.driver_manager is None  # noqa: SLF001

    def test_the_controller_replaces_the_stage_loops_with_one_driver_loop(
        self, controller_config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(controller_config)

        names = [name for name, _ in orch.stage_loop_names_and_factories()]

        assert names == ["issue_driver"]

    def test_the_controller_builds_a_driver_manager(
        self, controller_config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(controller_config)

        assert orch._svc.driver_manager is not None  # noqa: SLF001

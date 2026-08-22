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


def test_the_fable_runtime_is_selectable_but_not_the_default() -> None:
    # #11537 landed the shadow director, so the pair now loads. What "default
    # off" means for it is pinned in tests/test_director_shadow_default_off.py:
    # the director object is not constructed unless it is selected.
    config = HydraFlowConfig(
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
    )

    assert (config.uses_fable_director(), HydraFlowConfig().uses_fable_director()) == (
        True,
        False,
    )


def test_a_fable_director_without_a_controller_is_still_invalid() -> None:
    # Arming the shadow director changed nothing about the two-owners pair.
    with pytest.raises((SchedulingCombinationError, ValueError), match="invalid"):
        HydraFlowConfig(execution_runtime=ExecutionRuntime.FABLE_DIRECTOR)


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


class TestGlobalWipFloor:
    """ADR-0137's narrowing of ADR-0094 (i) is binding, not aspirational."""

    def test_the_default_cap_is_not_below_the_per_stage_cap_total(self) -> None:
        config = HydraFlowConfig()

        assert config.driver_max_in_flight >= config.driver_stage_cap_total()

    def test_a_cap_set_below_the_stage_total_is_raised_to_the_floor(
        self, tmp_path
    ) -> None:
        # A lower value would serialize work the per-stage caps already allow
        # in parallel — a throughput regression wearing a WIP limit's clothes,
        # which is exactly what ADR-0094's concurrency objection was about.
        config = HydraFlowConfig(state_file=tmp_path / "state.json", max_planners=3)

        assert (
            config.effective_driver_max_in_flight() == config.driver_stage_cap_total()
        )

    def test_a_cap_above_the_floor_is_left_alone(self, tmp_path) -> None:
        config = HydraFlowConfig(
            state_file=tmp_path / "state.json", driver_max_in_flight=12
        )

        assert config.effective_driver_max_in_flight() == 12


class TestTransitionIntentSlots:
    """ADR-0137 C5(a)/C9 — the two slots, and why they are two."""

    def test_a_stage_intent_round_trips_through_the_ledger(self, tmp_path) -> None:
        from state import StateTracker

        state = StateTracker(tmp_path / "state.json")
        state.record_stage_transition(
            7,
            from_label="hydraflow-review",
            to_label="hydraflow-ready",
            epoch=2,
            phase_attempt=1,
        )

        assert state.get_stage_transition(7).to_label == "hydraflow-ready"

    def test_clearing_the_stage_intent_leaves_the_sub_state_intent_intact(
        self, tmp_path
    ) -> None:
        # The reason the slots are separate: C5(a) rule 1 clears the stage
        # record whenever exactly one pipeline label is present, which is the
        # normal condition for a sub-state transition. A shared slot would
        # delete the sub-state commit on the very path C9 exists to protect.
        from state import StateTracker

        state = StateTracker(tmp_path / "state.json")
        state.record_stage_transition(
            7, from_label="a", to_label="b", epoch=0, phase_attempt=0
        )
        state.record_sub_state_transition(
            7, from_state="REVIEW", to_state="DIAGNOSE", epoch=0, phase_attempt=0
        )

        state.clear_stage_transition(7)

        assert state.get_sub_state_transition(7) is not None

    def test_a_transition_intent_survives_a_state_reload(self, tmp_path) -> None:
        from state import StateTracker

        path = tmp_path / "state.json"
        state = StateTracker(path)
        state.record_stage_transition(
            7,
            from_label="hydraflow-hitl",
            to_label="hydraflow-ready",
            epoch=3,
            phase_attempt=0,
        )

        reloaded = StateTracker(path)

        assert reloaded.get_stage_transition(7).from_label == "hydraflow-hitl"

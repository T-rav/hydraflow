"""The default-off invariant for the shadow Fable director (#11537).

#11535 set the standard this file has to meet: the honest reading of "default
off" is not "a flag is false" but "the object graph is the one the operator
already had". So these tests assert the director is **never constructed** rather
than constructed-and-dormant — and they assert it at two levels, because
#11537 introduces a distinction #11535 did not have:

* an operator on **Classic** has no driver and no director;
* an operator on the **deterministic controller** has drivers and *still* no
  director. That is the load-bearing one. ``issue_controller`` is now two
  presets, and someone opting into per-issue drivers must not silently acquire
  a Fable process along with them.

The mirror-image assertions under ``fable_director`` are here too, so this file
would also fail if opting in did nothing — a default-off test that cannot tell
"off" from "broken" proves nothing.

Every construction goes through the real ``HydraFlowOrchestrator``, so this
exercises ``build_services`` end to end rather than a config predicate on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from config import HydraFlowConfig
from scheduling_model import (
    FABLE_DIRECTOR,
    SELECTABLE_PRESETS,
    ExecutionRuntime,
    SchedulingModel,
    resolve_preset,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def classic_config(tmp_path: Path) -> HydraFlowConfig:
    return HydraFlowConfig(state_file=tmp_path / "state.json")


@pytest.fixture
def controller_config(tmp_path: Path) -> HydraFlowConfig:
    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
    )


@pytest.fixture
def director_config(tmp_path: Path) -> HydraFlowConfig:
    return HydraFlowConfig(
        state_file=tmp_path / "state.json",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
    )


def _orchestrator(config: HydraFlowConfig):
    from orchestrator import HydraFlowOrchestrator

    return HydraFlowOrchestrator(config)


# --------------------------------------------------------------------------
# The dials
# --------------------------------------------------------------------------


def test_a_fresh_config_does_not_use_a_fable_director() -> None:
    assert HydraFlowConfig().uses_fable_director() is False


def test_the_deterministic_controller_does_not_use_a_fable_director(
    controller_config: HydraFlowConfig,
) -> None:
    # The distinction #11537 introduces: opting into per-issue drivers must not
    # bring a Fable process with it.
    assert controller_config.uses_fable_director() is False


def test_opting_in_to_the_director_uses_it(
    director_config: HydraFlowConfig,
) -> None:
    assert director_config.uses_fable_director() is True


def test_the_director_preset_is_selectable_now_that_its_runtime_exists() -> None:
    # #11535 shipped this pair as UNARMED and a test pinned that choosing it
    # raised. #11537 lands the runtime, so the pair resolves — in SHADOW mode.
    preset = resolve_preset(
        SchedulingModel.ISSUE_CONTROLLER, ExecutionRuntime.FABLE_DIRECTOR
    )

    assert preset is FABLE_DIRECTOR


def test_selecting_the_director_does_not_arm_dispatch() -> None:
    # Selecting the observer and trusting the actuator are two decisions. The
    # second is #11541's, gated on ADR-0137 B5's evidence bar.
    assert FABLE_DIRECTOR.director_dispatch_armed is False


def test_no_selectable_preset_arms_dispatch() -> None:
    assert [p.name for p in SELECTABLE_PRESETS if p.director_dispatch_armed] == []


def test_a_director_without_a_controller_is_still_structurally_invalid(
    tmp_path: Path,
) -> None:
    # Two owners. Arming the director changed nothing about this pair.
    with pytest.raises(ValueError, match="invalid"):
        HydraFlowConfig(
            state_file=tmp_path / "state.json",
            execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        )


# --------------------------------------------------------------------------
# The object graph — the part that actually proves default-off
# --------------------------------------------------------------------------


class TestTheDirectorIsNeverConstructedUnlessSelected:
    def test_classic_builds_no_director(self, classic_config: HydraFlowConfig) -> None:
        orch = _orchestrator(classic_config)

        assert orch._svc.fable_director is None  # noqa: SLF001

    def test_the_deterministic_controller_builds_no_director(
        self, controller_config: HydraFlowConfig
    ) -> None:
        orch = _orchestrator(controller_config)

        assert orch._svc.fable_director is None  # noqa: SLF001

    def test_the_controllers_allocator_has_no_observer_attached(
        self, controller_config: HydraFlowConfig
    ) -> None:
        # Not merely "the director is None" — the allocator must not be holding
        # an observer of any kind, or a future collaborator could slip in
        # through the same seam without this test noticing.
        orch = _orchestrator(controller_config)

        assert orch._svc.driver_manager.has_observer is False  # noqa: SLF001

    def test_selecting_the_director_builds_one(
        self, director_config: HydraFlowConfig
    ) -> None:
        orch = _orchestrator(director_config)

        assert orch._svc.fable_director is not None  # noqa: SLF001

    def test_the_directors_allocator_has_it_attached_as_the_observer(
        self, director_config: HydraFlowConfig
    ) -> None:
        orch = _orchestrator(director_config)

        assert orch._svc.driver_manager.has_observer is True  # noqa: SLF001

    def test_the_director_preset_still_registers_only_the_driver_loop(
        self, director_config: HydraFlowConfig
    ) -> None:
        # The shadow director adds no loop of its own: it hangs off the driver's
        # boundary, so there is no second consumer of any stage queue and no
        # extra tick to reason about.
        orch = _orchestrator(director_config)

        names = [name for name, _ in orch.stage_loop_names_and_factories()]

        assert names == ["issue_driver"]


class TestTheDirectorFailsClosedAtConstruction:
    def test_missing_probe_evidence_refuses_to_build_a_director(
        self, director_config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ADR-0137's go is conditional on S4, and S4 asserts against committed
        # evidence. Without it the assertion cannot be armed, so the factory
        # must refuse to start rather than start with an observer that silently
        # verifies nothing.
        from director_sandbox import DirectorSandboxError

        monkeypatch.setattr(
            HydraFlowConfig,
            "director_probe_evidence_path",
            lambda self: self.state_file.parent / "absent.json",
        )

        with pytest.raises(DirectorSandboxError):
            _orchestrator(director_config)


class TestOperatorStatusSeparatesDesiredFromEffective:
    def test_desired_reports_the_selected_preset(
        self, director_config: HydraFlowConfig
    ) -> None:
        from dashboard_routes._scheduling_routes import _desired

        assert _desired(director_config)["execution_runtime"] == "fable_director"

    def test_desired_reports_that_dispatch_is_not_armed(
        self, director_config: HydraFlowConfig
    ) -> None:
        from dashboard_routes._scheduling_routes import _desired

        assert _desired(director_config)["director_dispatch_armed"] is False

    def test_effective_reports_a_detached_director_honestly(
        self, director_config: HydraFlowConfig
    ) -> None:
        # A director that fails its startup boundary proof is detached for the
        # run. Desired still reads ``fable_director``; effective must say that
        # nothing is observing, or an operator would believe otherwise.
        from dashboard_routes._scheduling_routes import _effective

        orch = _orchestrator(director_config)
        orch._svc.driver_manager.detach_observer()  # noqa: SLF001

        assert _effective(orch)["director_attached"] is False

    def test_effective_reports_an_attached_director(
        self, director_config: HydraFlowConfig
    ) -> None:
        from dashboard_routes._scheduling_routes import _effective

        assert _effective(_orchestrator(director_config))["director_attached"] is True

    def test_the_shadow_view_is_inactive_under_classic(
        self, classic_config: HydraFlowConfig
    ) -> None:
        from dashboard_routes._scheduling_routes import _shadow

        assert _shadow(_orchestrator(classic_config), 20)["active"] is False

    def test_the_shadow_view_reports_zero_workers_dispatched(
        self, director_config: HydraFlowConfig
    ) -> None:
        # In shadow mode this is an invariant, not a statistic.
        from dashboard_routes._scheduling_routes import _shadow

        view = _shadow(_orchestrator(director_config), 20)

        assert view["summary"]["workers_dispatched"] == 0

    def test_a_detached_director_makes_the_shadow_view_inactive_too(
        self, director_config: HydraFlowConfig
    ) -> None:
        # Keying ``active`` on the object's existence rather than on whether it
        # is attached would report the shadow section switched ON and the
        # director section switched OFF in the same response — the exact
        # confusion splitting desired from effective exists to prevent, and the
        # state an operator sees whenever preflight fails.
        from dashboard_routes._scheduling_routes import _shadow

        orch = _orchestrator(director_config)
        orch._svc.driver_manager.detach_observer()  # noqa: SLF001

        assert _shadow(orch, 20)["active"] is False

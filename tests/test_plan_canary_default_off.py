"""The two proofs the Plan canary is defined by (#11541).

#11634 set the standard for the first one and #11537 restated it: the honest
reading of "default off" is not *"a flag is false"* but *"the object graph is
the one the operator already had"*. So the first class below asserts the
dispatcher is **never constructed** — not constructed and dormant — through the
real ``HydraFlowOrchestrator``, at every point on the dial an operator can
occupy.

The second is the rollback. ADR-0141 D5's property, held to the same standard:
one field, live, empty by default, and clearing it disarms on the **next**
boundary with no restart, no other edit, and nothing to re-author before
arming again. The round trip is run, because a rollback nobody has re-armed
after is a rollback nobody has finished testing.

Both are written against the *predicate and the object graph* rather than
against a dispatch, because a proof that needs a real Sonnet worker to run is a
proof that never runs in CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from config import HydraFlowConfig
from driver_contracts import DriverPhase
from plan_broker import plan_canary_armed, plan_canary_covers
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

CANARY_REPO = "acme/widgets"


def _config(tmp_path: Path, **kwargs: object) -> HydraFlowConfig:
    base: dict[str, object] = {
        "state_file": tmp_path / "state.json",
        "repo": CANARY_REPO,
    }
    base.update(kwargs)
    return HydraFlowConfig(**base)  # type: ignore[arg-type]


def _director_config(tmp_path: Path, **kwargs: object) -> HydraFlowConfig:
    return _config(
        tmp_path,
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        **kwargs,
    )


def _orchestrator(config: HydraFlowConfig):
    from orchestrator import HydraFlowOrchestrator

    return HydraFlowOrchestrator(config)


def _dispatcher(orch):
    director = orch._svc.fable_director  # noqa: SLF001
    return None if director is None else director._dispatcher  # noqa: SLF001


# --------------------------------------------------------------------------
# Proof 1: default off is the object graph, not a flag
# --------------------------------------------------------------------------


class TestTheDispatcherIsNeverConstructedUnlessArmed:
    def test_a_fresh_config_arms_nothing(self) -> None:
        assert HydraFlowConfig().fable_plan_canary_armed() is False

    def test_classic_builds_no_dispatcher(self, tmp_path: Path) -> None:
        orch = _orchestrator(_config(tmp_path))

        assert orch._svc.fable_director is None  # noqa: SLF001

    def test_the_deterministic_controller_builds_no_dispatcher(
        self, tmp_path: Path
    ) -> None:
        orch = _orchestrator(
            _config(tmp_path, scheduling_model=SchedulingModel.ISSUE_CONTROLLER)
        )

        assert orch._svc.fable_director is None  # noqa: SLF001

    def test_a_shadow_director_with_no_canary_repo_builds_no_dispatcher(
        self, tmp_path: Path
    ) -> None:
        # The load-bearing one. Selecting the director is #11537's decision;
        # naming a canary repository is #11541's, and an operator who has made
        # only the first must have no actuator in their process at all.
        orch = _orchestrator(_director_config(tmp_path))

        assert _dispatcher(orch) is None

    def test_naming_another_repository_builds_no_dispatcher(
        self, tmp_path: Path
    ) -> None:
        orch = _orchestrator(
            _director_config(tmp_path, fable_plan_canary_repo="acme/other")
        )

        assert _dispatcher(orch) is None

    def test_naming_this_repository_builds_one(self, tmp_path: Path) -> None:
        # The mirror image, so the four assertions above cannot pass by the
        # feature being broken rather than off.
        orch = _orchestrator(
            _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)
        )

        assert _dispatcher(orch) is not None

    def test_arming_the_canary_adds_no_loop(self, tmp_path: Path) -> None:
        # The canary hangs off the driver's boundary like the observer does:
        # no second queue consumer, no extra tick, nothing new to reason about.
        orch = _orchestrator(
            _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)
        )

        assert [name for name, _ in orch.stage_loop_names_and_factories()] == [
            "issue_driver"
        ]

    def test_no_selectable_preset_arms_dispatch(self) -> None:
        # Arming stayed off the preset deliberately: a preset is fleet-wide and
        # would arm every repository the factory touches, which is the opposite
        # of a bounded slice.
        from scheduling_model import SELECTABLE_PRESETS

        assert [p.name for p in SELECTABLE_PRESETS if p.director_dispatch_armed] == []

    def test_a_canary_repo_without_a_director_arms_nothing(
        self, tmp_path: Path
    ) -> None:
        # Naming the repository under Classic must not arm an actuator that has
        # no director to be driven by.
        config = _config(tmp_path, fable_plan_canary_repo=CANARY_REPO)

        assert config.fable_plan_canary_armed() is False


# --------------------------------------------------------------------------
# Proof 2: one action, live, and reversible
# --------------------------------------------------------------------------


class TestClearingOneFieldIsTheWholeRollback:
    def test_the_dial_is_empty_by_default(self) -> None:
        assert HydraFlowConfig().fable_plan_canary_repo == ""

    def test_the_dial_is_registered_live(self) -> None:
        # The rollback depends on it: a dispatcher already constructed keeps
        # existing after a rollback, and what stops it running is this
        # predicate being re-read. A restart-required badge here would make the
        # rollback a restart.
        from settings_registry import SETTINGS

        assert SETTINGS["fable_plan_canary_repo"].live is True

    def test_the_dial_is_deliberately_not_env_overridable(self) -> None:
        # ADR-0141 D5's lesson, inherited rather than relearned: an env
        # override applies whenever a field is at its *default*, and the
        # disarmed value IS the default — so an env row would mean clearing the
        # field in the config file or the settings UI disarmed nothing, and the
        # next config load re-armed it. A rollback with two places to look is
        # not one action.
        from config import _ENV_STR_OVERRIDES

        assert not [
            row for row in _ENV_STR_OVERRIDES if row[0] == "fable_plan_canary_repo"
        ]

    def test_arming_covers_a_plan_boundary(self, tmp_path: Path) -> None:
        config = _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)

        assert plan_canary_covers(config, phase=DriverPhase.PLAN) is True

    def test_clearing_the_field_disarms_without_a_restart(self, tmp_path: Path) -> None:
        # The same object, edited the way the settings PATCH route edits it.
        config = _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)
        object.__setattr__(config, "fable_plan_canary_repo", "")

        assert plan_canary_covers(config, phase=DriverPhase.PLAN) is False

    def test_re_arming_after_a_rollback_needs_nothing_re_authored(
        self, tmp_path: Path
    ) -> None:
        # The whole round trip: armed, disarmed, re-armed, with no policy file,
        # no second dial and no restart in between.
        config = _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)
        armed = plan_canary_covers(config, phase=DriverPhase.PLAN)
        object.__setattr__(config, "fable_plan_canary_repo", "")
        rolled_back = plan_canary_covers(config, phase=DriverPhase.PLAN)
        object.__setattr__(config, "fable_plan_canary_repo", CANARY_REPO)
        re_armed = plan_canary_covers(config, phase=DriverPhase.PLAN)

        assert (armed, rolled_back, re_armed) == (True, False, True)

    def test_a_rollback_leaves_the_director_observing(self, tmp_path: Path) -> None:
        # Rolling the canary back returns the repository to #11537's shadow
        # mode, not to Classic: the evidence keeps accruing while nothing is
        # dispatched, which is the state an operator wants after a rollback.
        config = _director_config(tmp_path, fable_plan_canary_repo=CANARY_REPO)
        orch = _orchestrator(config)
        object.__setattr__(config, "fable_plan_canary_repo", "")

        assert orch._svc.driver_manager.has_observer is True  # noqa: SLF001

    @pytest.mark.parametrize(
        "dialled",
        [
            pytest.param("acme-widgets", id="runtime-slug"),
            pytest.param("widgets", id="bare-name"),
            pytest.param("acme/widgets/extra", id="too-many-segments"),
        ],
    )
    def test_a_dial_that_could_arm_nothing_is_refused_at_load(
        self, tmp_path: Path, dialled: str
    ) -> None:
        # Failing closed is the right behaviour and the wrong silence: an
        # operator who typed the runtime slug would believe a repository was
        # brokered while every boundary stayed shadow.
        with pytest.raises(ValueError, match="canonical"):
            _director_config(tmp_path, fable_plan_canary_repo=dialled)

    def test_an_empty_dial_is_the_valid_disarmed_default(self, tmp_path: Path) -> None:
        assert (
            plan_canary_armed(_director_config(tmp_path, fable_plan_canary_repo=""))
            is False
        )

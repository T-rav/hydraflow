"""The two proofs the Implement canary is defined by (#11542).

#11634 set the standard and #11541 restated it: the honest reading of "default
off" is not *"a flag is false"* but *"the object graph is the one the operator
already had"*. So the first class below asserts the implement dispatcher is
**never constructed** — not constructed and dormant — through the real
``HydraFlowOrchestrator``, at every point on the dial an operator can occupy.

This phase adds a point the phase before it did not have, and it is the one
that matters most here: **an operator running the Plan canary today**. Arming
one dial must arm nothing about the other, or "widen one role boundary at a
time" is a sentence rather than a property.

The second class is the rollback, held to ADR-0141 D5's standard: one field,
live, empty by default, clearing it disarms on the **next** boundary with no
restart and nothing to re-author before arming again. The round trip is run,
because a rollback nobody has re-armed after is a rollback nobody has finished
testing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from config import HydraFlowConfig
from driver_contracts import DriverPhase
from implement_broker import implement_canary_armed, implement_canary_covers
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


def _directed(tmp_path: Path, **kwargs: object) -> HydraFlowConfig:
    return _config(
        tmp_path,
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        **kwargs,
    )


def _built_director(settings: HydraFlowConfig):
    from orchestrator import HydraFlowOrchestrator

    return HydraFlowOrchestrator(settings)._svc.fable_director  # noqa: SLF001


def _writer_actuator(settings: HydraFlowConfig):
    """The implement dispatcher this configuration actually builds, if any."""
    built = _built_director(settings)
    return None if built is None else built._implement_dispatcher  # noqa: SLF001


# --------------------------------------------------------------------------
# Proof 1: default off is the object graph, not a flag
# --------------------------------------------------------------------------


class TestNoWriterActuatorExistsUnlessArmed:
    def test_an_untouched_installation_arms_no_writer(self) -> None:
        assert HydraFlowConfig().fable_implement_canary_armed() is False

    @pytest.mark.parametrize(
        "dials",
        [
            pytest.param({}, id="classic"),
            pytest.param(
                {"scheduling_model": SchedulingModel.ISSUE_CONTROLLER},
                id="deterministic-controller",
            ),
        ],
    )
    def test_a_configuration_without_a_director_builds_none(
        self, tmp_path: Path, dials: dict[str, object]
    ) -> None:
        assert _built_director(_config(tmp_path, **dials)) is None

    def test_a_shadow_director_alone_builds_no_writer_actuator(
        self, tmp_path: Path
    ) -> None:
        assert _writer_actuator(_directed(tmp_path)) is None

    def test_the_plan_canary_alone_builds_no_writer_actuator(
        self, tmp_path: Path
    ) -> None:
        # The load-bearing one for THIS phase. An operator who armed #11541's
        # dial and nothing else must have no object in their process that can
        # measure a worktree, take a writer lease, or start a writer.
        settings = _directed(tmp_path, fable_plan_canary_repo=CANARY_REPO)

        assert _writer_actuator(settings) is None

    def test_a_writer_dial_naming_another_repository_builds_none(
        self, tmp_path: Path
    ) -> None:
        settings = _directed(tmp_path, fable_implement_canary_repo="acme/other")

        assert _writer_actuator(settings) is None

    def test_naming_this_repository_builds_the_writer_actuator(
        self, tmp_path: Path
    ) -> None:
        # The mirror image, so the four assertions above cannot pass by the
        # feature being broken rather than off.
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)

        assert _writer_actuator(settings) is not None

    def test_arming_the_writer_canary_introduces_no_loop(self, tmp_path: Path) -> None:
        # It hangs off the driver's boundary like the observer and the Plan
        # actuator do: no second queue consumer, no extra tick, nothing new for
        # an operator to reason about.
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)
        orchestrator = _orchestrator_for(settings)

        assert [n for n, _ in orchestrator.stage_loop_names_and_factories()] == [
            "issue_driver"
        ]

    def test_a_writer_dial_under_classic_arms_nothing(self, tmp_path: Path) -> None:
        # Naming the repository without selecting the director must not arm an
        # actuator that has no director to be driven by.
        settings = _config(tmp_path, fable_implement_canary_repo=CANARY_REPO)

        assert settings.fable_implement_canary_armed() is False


def _orchestrator_for(settings: HydraFlowConfig):
    from orchestrator import HydraFlowOrchestrator

    return HydraFlowOrchestrator(settings)


# --------------------------------------------------------------------------
# Proof 2: one action, live, and reversible
# --------------------------------------------------------------------------


class TestClearingTheWriterDialIsTheWholeRollback:
    def test_the_writer_dial_starts_empty(self) -> None:
        assert HydraFlowConfig().fable_implement_canary_repo == ""

    @pytest.mark.parametrize(
        "dial",
        [
            pytest.param("fable_implement_canary_repo", id="repository"),
            pytest.param("fable_implement_worker_timeout_seconds", id="budget"),
        ],
    )
    def test_both_writer_dials_are_registered_live(self, dial: str) -> None:
        # The rollback depends on the first being live: an actuator already
        # constructed keeps existing after a rollback, and what stops it running
        # is the predicate being re-read. A restart-required badge would make
        # the rollback a restart.
        from settings_registry import SETTINGS

        assert SETTINGS[dial].live is True

    @pytest.mark.parametrize(
        "dial",
        [
            pytest.param("fable_implement_canary_repo", id="repository"),
            pytest.param("fable_implement_worker_timeout_seconds", id="budget"),
        ],
    )
    def test_no_writer_dial_is_environment_overridable(self, dial: str) -> None:
        # ADR-0141 D5's lesson, inherited rather than relearned for a third
        # time. An env override applies whenever a field is at its *default*,
        # and for the repository dial the disarmed value IS the default — so a
        # row would mean clearing it in the config file or the settings UI
        # disarmed nothing and the next load re-armed it. The budget dial is
        # listed beside it because a canary whose rollback is one action and
        # whose budget is two places to look is not one story.
        from config import _ENV_INT_OVERRIDES, _ENV_STR_OVERRIDES

        rows = [*_ENV_STR_OVERRIDES, *_ENV_INT_OVERRIDES]
        assert [row for row in rows if row[0] == dial] == []

    def test_the_armed_dial_covers_an_implement_boundary(self, tmp_path: Path) -> None:
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)

        assert implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT) is True

    def test_emptying_the_dial_disarms_with_no_restart(self, tmp_path: Path) -> None:
        # The same object, edited the way the settings PATCH route edits it.
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)
        object.__setattr__(settings, "fable_implement_canary_repo", "")

        assert implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT) is False

    def test_the_round_trip_needs_nothing_re_authored(self, tmp_path: Path) -> None:
        # Armed, disarmed, re-armed, with no policy file, no second dial and no
        # restart in between.
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)
        was_armed = implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT)
        object.__setattr__(settings, "fable_implement_canary_repo", "")
        rolled_back = implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT)
        object.__setattr__(settings, "fable_implement_canary_repo", CANARY_REPO)
        re_armed = implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT)

        assert (was_armed, rolled_back, re_armed) == (True, False, True)

    def test_rolling_the_writer_canary_back_leaves_the_plan_canary_armed(
        self, tmp_path: Path
    ) -> None:
        # The two dials are independent in both directions, and this is the
        # direction an operator actually exercises: back out the writers, keep
        # the plan evidence accruing.
        from plan_broker import plan_canary_covers

        settings = _directed(
            tmp_path,
            fable_plan_canary_repo=CANARY_REPO,
            fable_implement_canary_repo=CANARY_REPO,
        )
        object.__setattr__(settings, "fable_implement_canary_repo", "")

        assert plan_canary_covers(settings, phase=DriverPhase.PLAN) is True

    def test_rolling_back_leaves_the_director_observing(self, tmp_path: Path) -> None:
        # Rolling back returns the repository to shadow mode, not to Classic:
        # the evidence keeps accruing while nothing is dispatched, which is the
        # state an operator wants after a rollback.
        settings = _directed(tmp_path, fable_implement_canary_repo=CANARY_REPO)
        orchestrator = _orchestrator_for(settings)
        object.__setattr__(settings, "fable_implement_canary_repo", "")

        assert orchestrator._svc.driver_manager.has_observer is True  # noqa: SLF001

    @pytest.mark.parametrize(
        "typed",
        [
            pytest.param("acme-widgets", id="runtime-slug"),
            pytest.param("widgets", id="bare-name"),
            pytest.param("acme/widgets/extra", id="too-many-segments"),
        ],
    )
    def test_a_writer_dial_that_could_arm_nothing_is_refused_at_load(
        self, tmp_path: Path, typed: str
    ) -> None:
        # Failing closed is right and failing closed silently is wrong: an
        # operator who typed the runtime slug would believe writers were
        # brokered while every boundary stayed shadow.
        with pytest.raises(ValueError, match="canonical"):
            _directed(tmp_path, fable_implement_canary_repo=typed)

    def test_an_empty_writer_dial_is_the_valid_disarmed_default(
        self, tmp_path: Path
    ) -> None:
        assert (
            implement_canary_armed(_directed(tmp_path, fable_implement_canary_repo=""))
            is False
        )

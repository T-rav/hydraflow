"""The two proofs the Review canary is defined by (#11543).

The third canary, held to the standard its two siblings set. The honest reading
of "default off" is not *"a flag is false"* but *"the object graph is the one
the operator already had"*, and the honest reading of a rollback is *one live
field, cleared, with nothing to re-author before arming again*.

This phase adds two points the phases before it did not have, and both are
about the boundary rather than the dial:

- **arming a reviewer must arm no writer.** ``WORKER_CATALOG`` legalises a
  ``DEBUGGER`` at ``REVIEW`` and a debugger holds the issue worktree, so a menu
  derived from the phase alone would let this dial widen the *write* boundary
  while every dial an operator reads as a writer dial stayed empty. That is the
  epic's "widen one role boundary at a time" broken silently, and the property
  is asserted here against the catalogue rather than against a hardcoded list.
- **the third dial is independent of the first two in both directions.** An
  operator running Plan and Implement today must not wake up dispatching
  judges, and an operator arming a judge must not widen either writer.

The behavioural half — arming actually dispatches, clearing actually stops —
lives in ``tests/regressions/test_issue_11543_outside_the_slice.py``, which runs
a fully wired director over covered and uncovered boundaries. This file is the
composition root's half: what ``build_services`` constructs, and what the
predicate it wired answers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from config import HydraFlowConfig
from driver_contracts import WORKER_CATALOG, DriverPhase, WriteScope
from review_broker import (
    review_canary_armed,
    review_canary_covers,
    review_roles_for_review_phase,
)
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


def _orchestrator_for(settings: HydraFlowConfig):
    from orchestrator import HydraFlowOrchestrator

    return HydraFlowOrchestrator(settings)


def _built_director(settings: HydraFlowConfig):
    return _orchestrator_for(settings)._svc.fable_director  # noqa: SLF001


def _review_actuator(settings: HydraFlowConfig):
    """The review dispatcher this configuration actually builds, if any."""
    built = _built_director(settings)
    return None if built is None else built._review_dispatcher  # noqa: SLF001


# --------------------------------------------------------------------------
# Proof 1: default off is the object graph, not a flag
# --------------------------------------------------------------------------


class TestNoReviewerIsDispatchedUnlessArmed:
    def test_an_untouched_installation_arms_no_reviewer(self) -> None:
        assert HydraFlowConfig().fable_review_canary_armed() is False

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
    def test_a_configuration_without_a_director_builds_no_review_actuator(
        self, tmp_path: Path, dials: dict[str, object]
    ) -> None:
        """Where default-off is actually true: no director, therefore no
        review actuator at all. Everywhere else it is the predicate that holds.

        Asserted through ``_review_actuator`` rather than on the director, so
        the statement is about what this file's subject is. Be precise about
        how much that buys, though: for both inputs below ``_built_director``
        is ``None`` — neither selects ``FABLE_DIRECTOR`` — so the helper
        short-circuits and ``_review_dispatcher`` is never actually read. For
        these two cases this is therefore equivalent to "no director", which
        ``tests/test_implement_canary_default_off.py`` also owns.

        Saying so rather than claiming a derivation this does not perform: the
        case where the actuator EXISTS and is inert is a different fact, and it
        is pinned separately by
        ``test_a_director_is_built_with_its_review_actuator_ready_but_inert``,
        which is the test that genuinely reads ``_review_dispatcher``.
        """
        assert _review_actuator(_config(tmp_path, **dials)) is None

    def test_a_shadow_director_alone_dispatches_no_reviewer(
        self, tmp_path: Path
    ) -> None:
        settings = _directed(tmp_path)
        _orchestrator_for(settings)

        assert review_canary_covers(settings, phase=DriverPhase.REVIEW) is False

    @pytest.mark.parametrize(
        "armed",
        [
            pytest.param({"fable_plan_canary_repo": CANARY_REPO}, id="plan-only"),
            pytest.param(
                {"fable_implement_canary_repo": CANARY_REPO}, id="implement-only"
            ),
            pytest.param(
                {
                    "fable_plan_canary_repo": CANARY_REPO,
                    "fable_implement_canary_repo": CANARY_REPO,
                },
                id="plan-and-implement",
            ),
        ],
    )
    def test_the_older_canaries_alone_dispatch_no_reviewer(
        self, tmp_path: Path, armed: dict[str, object]
    ) -> None:
        # The load-bearing one for THIS phase, at every point on the two dials
        # that already exist. An operator running the Plan canary, the
        # Implement canary or both must not wake up dispatching judges.
        settings = _directed(tmp_path, **armed)
        _orchestrator_for(settings)

        assert review_canary_covers(settings, phase=DriverPhase.REVIEW) is False

    def test_a_review_dial_naming_another_repository_dispatches_nothing(
        self, tmp_path: Path
    ) -> None:
        settings = _directed(tmp_path, fable_review_canary_repo="acme/other")
        _orchestrator_for(settings)

        assert review_canary_covers(settings, phase=DriverPhase.REVIEW) is False

    def test_a_director_is_built_with_its_review_actuator_ready_but_inert(
        self, tmp_path: Path
    ) -> None:
        # The shape #11657 established and this phase inherited rather than
        # relearned: the actuator is ALWAYS constructed under a director, so
        # arming is live in both directions. What makes it inert is the
        # predicate, and the two are asserted together so neither can be
        # mistaken for the other.
        settings = _directed(tmp_path)

        assert _review_actuator(settings) is not None
        assert review_canary_covers(settings, phase=DriverPhase.REVIEW) is False

    def test_arming_reaches_the_next_boundary_without_a_restart(
        self, tmp_path: Path
    ) -> None:
        # The predicate the ORCHESTRATOR built is what is asked, not a fresh
        # call to ``review_canary_covers``. The latter is a pure function of
        # the config and would pass with the whole composition root deleted;
        # this reads the closure ``build_services`` wired into the director, so
        # deleting ``review_is_covered=`` reddens it.
        settings = _directed(tmp_path)
        director = _built_director(settings)
        assert director is not None
        before = director._review_is_covered(DriverPhase.REVIEW)  # noqa: SLF001

        object.__setattr__(settings, "fable_review_canary_repo", CANARY_REPO)

        assert (before, director._review_is_covered(DriverPhase.REVIEW)) == (  # noqa: SLF001
            False,
            True,
        )

    def test_arming_the_review_canary_introduces_no_loop(self, tmp_path: Path) -> None:
        # It hangs off the driver's boundary like the observer and the two
        # older actuators do: no second queue consumer, no extra tick.
        settings = _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)
        orchestrator = _orchestrator_for(settings)

        assert [n for n, _ in orchestrator.stage_loop_names_and_factories()] == [
            "issue_driver"
        ]

    def test_a_review_dial_under_classic_arms_nothing(self, tmp_path: Path) -> None:
        # Naming the repository without selecting the director must not arm an
        # actuator that has no director to be driven by.
        settings = _config(tmp_path, fable_review_canary_repo=CANARY_REPO)

        assert settings.fable_review_canary_armed() is False


# --------------------------------------------------------------------------
# Proof 2: arming a reviewer arms no writer
# --------------------------------------------------------------------------


class TestTheReviewDialWidensExactlyOneBoundary:
    def test_every_role_this_dial_can_arm_writes_nothing(self) -> None:
        # Against the catalogue, not against a list written here. A hardcoded
        # expectation would be a second description of ``WORKER_CATALOG``, free
        # to agree with a menu that had silently started admitting a writer.
        menu = review_roles_for_review_phase()

        assert menu
        assert {WORKER_CATALOG[role].write_scope for role in menu} == {WriteScope.NONE}

    def test_the_catalogue_legalises_a_writer_this_dial_still_refuses(self) -> None:
        """The negative control that makes the assertion above non-vacuous.

        Without it, ``review_roles_for_review_phase`` could return the whole
        REVIEW phase unfiltered and the test above would still pass on a
        catalogue that happened to hold no write-scoped REVIEW role. This
        asserts the catalogue DOES hold one and the menu still excludes it, so
        deleting the ``WriteScope.NONE`` filter reddens rather than passing on
        a coincidence.
        """
        catalogued = {
            role
            for role, entry in WORKER_CATALOG.items()
            if DriverPhase.REVIEW in entry.allowed_phases
        }
        writers = {
            role
            for role in catalogued
            if WORKER_CATALOG[role].write_scope is not WriteScope.NONE
        }

        assert writers, "the catalogue no longer legalises a writer at REVIEW"
        assert not (writers & review_roles_for_review_phase())

    def test_arming_the_reviewer_covers_no_writer_phase(self, tmp_path: Path) -> None:
        # The dial-level statement of the same property: this dial covers
        # REVIEW and nothing else, so neither writer boundary is widened by it.
        from implement_broker import implement_canary_covers
        from plan_broker import plan_canary_covers

        settings = _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)

        assert (
            review_canary_covers(settings, phase=DriverPhase.REVIEW),
            implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT),
            plan_canary_covers(settings, phase=DriverPhase.PLAN),
        ) == (True, False, False)


# --------------------------------------------------------------------------
# Proof 3: one action, live, and reversible
# --------------------------------------------------------------------------


class TestClearingTheReviewDialIsTheWholeRollback:
    def test_the_review_dial_starts_empty(self) -> None:
        assert HydraFlowConfig().fable_review_canary_repo == ""

    @pytest.mark.parametrize(
        "dial",
        [
            pytest.param("fable_review_canary_repo", id="repository"),
            pytest.param("fable_review_worker_timeout_seconds", id="budget"),
        ],
    )
    def test_both_review_dials_are_registered_live(self, dial: str) -> None:
        # The rollback depends on the first being live: an actuator already
        # constructed keeps existing after a rollback, and what stops it running
        # is the predicate being re-read.
        from settings_registry import SETTINGS

        assert SETTINGS[dial].live is True

    def test_the_armed_dial_covers_a_review_boundary(self, tmp_path: Path) -> None:
        settings = _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)

        assert review_canary_covers(settings, phase=DriverPhase.REVIEW) is True

    def test_the_round_trip_needs_nothing_re_authored(self, tmp_path: Path) -> None:
        # Armed, disarmed, re-armed, with no policy file, no second dial and no
        # restart in between. A rollback nobody has re-armed after is a
        # rollback nobody has finished testing.
        settings = _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)
        was_armed = review_canary_covers(settings, phase=DriverPhase.REVIEW)
        object.__setattr__(settings, "fable_review_canary_repo", "")
        rolled_back = review_canary_covers(settings, phase=DriverPhase.REVIEW)
        object.__setattr__(settings, "fable_review_canary_repo", CANARY_REPO)
        re_armed = review_canary_covers(settings, phase=DriverPhase.REVIEW)

        assert (was_armed, rolled_back, re_armed) == (True, False, True)

    def test_rolling_the_review_canary_back_leaves_the_writers_armed(
        self, tmp_path: Path
    ) -> None:
        # Independence in the direction an operator actually exercises: back
        # out the judges, keep the writers running.
        from implement_broker import implement_canary_covers

        settings = _directed(
            tmp_path,
            fable_implement_canary_repo=CANARY_REPO,
            fable_review_canary_repo=CANARY_REPO,
        )
        object.__setattr__(settings, "fable_review_canary_repo", "")

        assert (
            implement_canary_covers(settings, phase=DriverPhase.IMPLEMENT),
            review_canary_covers(settings, phase=DriverPhase.REVIEW),
        ) == (True, False)

    def test_rolling_back_returns_the_repository_to_shadow_mode(
        self, tmp_path: Path
    ) -> None:
        # Both halves: the dial's own predicate, and the observer still being
        # attached — the second means something only beside the contrast in
        # ``test_implement_canary_default_off``, where it is genuinely False
        # for a directorless controller.
        settings = _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)
        orchestrator = _orchestrator_for(settings)
        object.__setattr__(settings, "fable_review_canary_repo", "")
        manager = orchestrator._svc.driver_manager  # noqa: SLF001
        # Narrowed rather than accessed through the Optional: a manager that
        # came back None would otherwise raise an AttributeError that reads as
        # a crash instead of as the wiring being gone.
        assert manager is not None

        assert (
            review_canary_covers(settings, phase=DriverPhase.REVIEW),
            manager.has_observer,
        ) == (False, True)

    @pytest.mark.parametrize(
        "typed",
        [
            pytest.param("acme-widgets", id="runtime-slug"),
            pytest.param("widgets", id="bare-name"),
            pytest.param("acme/widgets/extra", id="too-many-segments"),
        ],
    )
    def test_a_review_dial_that_could_arm_nothing_is_refused_at_load(
        self, tmp_path: Path, typed: str
    ) -> None:
        # Failing closed is right and failing closed silently is wrong: an
        # operator who typed the runtime slug would believe judges were
        # brokered while every REVIEW boundary stayed shadow.
        with pytest.raises(ValueError, match="canonical"):
            _directed(tmp_path, fable_review_canary_repo=typed)

    def test_an_empty_review_dial_is_the_valid_disarmed_default(
        self, tmp_path: Path
    ) -> None:
        assert (
            review_canary_armed(_directed(tmp_path, fable_review_canary_repo=""))
            is False
        )


# --------------------------------------------------------------------------
# Proof 4: the operator can see that arming happened
# --------------------------------------------------------------------------


class TestTheStatusEndpointSeesEveryArmedCanary:
    """``director_dispatch_armed`` asked only the PLAN dial until #11543.

    That was the whole story at #11541 and wrong by two dials by P5. An
    operator who armed the Implement or the Review canary was told dispatch was
    not armed — which is the exact failure the route's own docstring says the
    field exists to prevent, arriving through a new dial rather than through
    the preset it was written against.
    """

    @staticmethod
    def _desired(settings: HydraFlowConfig) -> dict[str, object]:
        from dashboard_routes._scheduling_routes import _desired

        return _desired(settings)

    def test_an_unarmed_director_reports_no_dispatch(self, tmp_path: Path) -> None:
        # The negative control. Without it, a field hardcoded to True would
        # pass every assertion below.
        desired = self._desired(_directed(tmp_path))

        assert desired["director_dispatch_armed"] is False
        assert desired["canaries_armed"] == {
            "plan": False,
            "implement": False,
            "review": False,
        }

    @pytest.mark.parametrize(
        ("dial", "row"),
        [
            pytest.param("fable_plan_canary_repo", "plan", id="plan"),
            pytest.param("fable_implement_canary_repo", "implement", id="implement"),
            pytest.param("fable_review_canary_repo", "review", id="review"),
        ],
    )
    def test_arming_any_canary_reports_dispatch_armed(
        self, tmp_path: Path, dial: str, row: str
    ) -> None:
        # Parametrised over the dials rather than written for the new one, per
        # the parametrised-guards standard: the field's subject is the SET of
        # canaries, so the guard must iterate that set.
        desired = self._desired(_directed(tmp_path, **{dial: CANARY_REPO}))

        assert desired["director_dispatch_armed"] is True
        assert desired["canaries_armed"][row] is True

    def test_the_aggregate_and_the_detail_cannot_disagree(self, tmp_path: Path) -> None:
        # Derived rather than re-listed: the aggregate is ``any()`` over the
        # same map the detail is read from, so a fourth canary reaches both
        # answers by being added once.
        desired = self._desired(
            _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)
        )

        assert desired["director_dispatch_armed"] is any(
            desired["canaries_armed"].values()
        )

    def test_the_armed_repository_is_named_per_dial(self, tmp_path: Path) -> None:
        # An operator needs to know WHICH repository, not only that something
        # is armed — the plan dial has been named since #11541 and the other
        # two were invisible.
        desired = self._desired(
            _directed(tmp_path, fable_review_canary_repo=CANARY_REPO)
        )

        assert desired["review_canary_repo"] == CANARY_REPO
        assert desired["implement_canary_repo"] == ""

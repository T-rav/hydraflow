"""One rule, swept over every registered canary (#11716).

``plan_broker``, ``implement_broker`` and ``review_broker`` state the same
three-clause rule, and ``HydraFlowConfig`` states the arming half a second
time. #11714 pinned the two clauses that had gone unguarded — the off-switch
and clause 2's canonicalisation — by writing the pin six times. This is the
seventh copy NOT being written: the properties below are parametrised over
``canary_registry.registered_canaries()``, so a fourth canary inherits every
one of them or reddens on the way in.

Each property drives the LIVE predicate. Nothing here reads source text, and
nothing re-implements a clause: a conformance test that restates the rule it
is checking is a second copy of the rule, which is the finding rather than the
fix (``docs/standards/parametrised_guards/README.md``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.architecture.canary_registry import Canary, registered_canaries

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

CANARIES: tuple[Canary, ...] = registered_canaries()
_IDS = [canary.name for canary in CANARIES]

#: A repository whose canonical form differs from its spelling. Clause 2
#: canonicalises BOTH operands; ``canonicalize_repo`` lower-cases and neither
#: field validator does, so a dial typed in one case against a repo configured
#: in another is the operator-visible form of the bug (#11716).
MIXED_CASE_REPO = "Acme/Widget"
CANONICAL_REPO = "acme/widget"


def _config(tmp_path: Path, **fields: object):
    from config import HydraFlowConfig
    from scheduling_model import ExecutionRuntime, SchedulingModel

    base: dict[str, object] = {
        "state_file": tmp_path / "state.json",
        "repo": CANONICAL_REPO,
        "scheduling_model": SchedulingModel.ISSUE_CONTROLLER,
        "execution_runtime": ExecutionRuntime.FABLE_DIRECTOR,
    }
    base.update(fields)
    return HydraFlowConfig(**base)  # type: ignore[arg-type]


def _force(config, **fields: object):
    """Install values the field validators refuse, bypassing validation.

    Both dial and ``repo`` have validators that reject a lossy slug outright,
    so the isolating cases below cannot be constructed the ordinary way. That
    is not a reason to skip them: the predicate's own canonicalisation is the
    second line of defence for values that skip validation
    (``model_construct``, ``model_copy``, a future default change), and it is
    the line that went unpinned in all six places (#11716). Deleting it must
    still redden, which needs a config carrying the value.
    """
    for name, value in fields.items():
        object.__setattr__(config, name, value)
    return config


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_an_armed_canary_covers_its_own_boundary(canary: Canary, tmp_path) -> None:
    """Non-vacuity, and it comes first deliberately.

    Every property below asserts a ``False``. A predicate wired to the wrong
    dial, or one that returns ``False`` unconditionally, satisfies all of them
    — which is how ``plan_canary_covers`` reading the *review* dial stayed
    green once already. This is the assertion that makes the rest mean
    something.
    """
    config = _config(tmp_path, **{canary.dial: CANONICAL_REPO})

    assert canary.covers(config, phase=canary.phase) is True


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_the_off_switch_covers_nothing(canary: Canary, tmp_path) -> None:
    """Clause 1. Deleting it survived the suite in 5 of 6 places (#11716).

    The isolating case has to use a repository that is itself unidentifiable,
    because an empty dial and a repo that canonicalises to ``None`` compare
    equal without the guard — which is exactly how the deletion stayed green.
    """
    for repo in (CANONICAL_REPO, "not-a-slug"):
        config = _force(_config(tmp_path), repo=repo, **{canary.dial: ""})

        assert canary.covers(config, phase=canary.phase) is False, repo
        assert canary.armed(config) is False, repo
        assert canary.badge(config) is False, repo


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_clause_two_canonicalises_the_configured_repo(canary: Canary, tmp_path) -> None:
    """Dropping ``canonicalize_repo`` on the ``config.repo`` operand survived
    in **all six** places. An armed canary then covered nothing, silently."""
    config = _config(tmp_path, repo=MIXED_CASE_REPO, **{canary.dial: CANONICAL_REPO})

    assert canary.covers(config, phase=canary.phase) is True
    assert canary.badge(config) is True


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_clause_two_canonicalises_the_dial(canary: Canary, tmp_path) -> None:
    """The other operand. One vocabulary, one normalisation — a fix that
    strips or lowers only one side is the shape ``admit_dispatch``'s lineage
    fence had to be corrected for twice."""
    config = _config(tmp_path, **{canary.dial: MIXED_CASE_REPO})

    assert canary.covers(config, phase=canary.phase) is True
    assert canary.badge(config) is True


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_a_lossy_dial_arms_nothing(canary: Canary, tmp_path) -> None:
    """A slug that cannot round-trip is not a bound (ADR-0139 D2)."""
    for lossy in ("widget", "acme/widget/extra", "acme-widget"):
        config = _force(_config(tmp_path), **{canary.dial: lossy})

        assert canary.covers(config, phase=canary.phase) is False, lossy
        assert canary.armed(config) is False, lossy
        assert canary.badge(config) is False, lossy


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_another_repository_is_outside_the_bound(canary: Canary, tmp_path) -> None:
    config = _config(tmp_path, repo="other/repo", **{canary.dial: CANONICAL_REPO})

    assert canary.covers(config, phase=canary.phase) is False
    assert canary.badge(config) is False


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_clause_three_holds_every_other_phase_outside(canary: Canary, tmp_path) -> None:
    """Clause 3, swept over the whole phase enum rather than one neighbour.

    ``None`` is included because the driver hands a phase through and an
    absent one must not be read as "any": a canary that covered ``None`` would
    arm every boundary that failed to state where it was.
    """
    from driver_contracts import DriverPhase

    config = _config(tmp_path, **{canary.dial: CANONICAL_REPO})
    others = [phase for phase in DriverPhase if phase is not canary.phase]

    for phase in [*others, None]:
        assert canary.covers(config, phase=phase) is False, phase


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_arming_one_canary_arms_no_other(canary: Canary, tmp_path) -> None:
    """The bound is per phase. Arming Plan must not dispatch a writer."""
    config = _config(tmp_path, **{canary.dial: CANONICAL_REPO})

    for other in CANARIES:
        if other.name == canary.name:
            continue
        assert other.covers(config, phase=other.phase) is False, other.name
        assert other.armed(config) is False, other.name
        assert other.badge(config) is False, other.name


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_the_badge_needs_the_director_as_well_as_the_dial(
    canary: Canary, tmp_path
) -> None:
    """Two operator decisions, not one. Selecting the director is
    restart-required and naming the canary repository is live; collapsing them
    is how "we turned on the observer" becomes "we turned on the actuator"."""
    from scheduling_model import ExecutionRuntime

    config = _config(
        tmp_path,
        execution_runtime=ExecutionRuntime.STAGE_SUBPROCESS,
        **{canary.dial: CANONICAL_REPO},
    )

    assert canary.badge(config) is False


@pytest.mark.parametrize("canary", CANARIES, ids=_IDS)
def test_the_dial_is_read_per_boundary_not_captured(canary: Canary, tmp_path) -> None:
    """A live badge over a captured value is the lie ``settings_registry``
    forbids: an operator who has to restart the factory to disarm a canary
    does not have a canary switch."""
    config = _config(tmp_path, **{canary.dial: CANONICAL_REPO})
    was_armed = canary.covers(config, phase=canary.phase)

    _force(config, **{canary.dial: ""})
    disarmed = canary.covers(config, phase=canary.phase)
    _force(config, **{canary.dial: CANONICAL_REPO})
    re_armed = canary.covers(config, phase=canary.phase)

    assert (was_armed, disarmed, re_armed) == (True, False, True)


# ---------------------------------------------------------------------------
# The refusal vocabulary the canaries share (#11716, residue 1)
# ---------------------------------------------------------------------------


def _phase_rows() -> tuple[object, ...]:
    """Every ``PHASE_NOT_*`` refusal reason, derived from the enum.

    By reference to ``PlanRouteReason``, not a re-typed list of three: a fourth
    canary adds a fourth member and it joins this sweep on the way in.
    """
    from plan_broker import PlanRouteReason

    return tuple(
        reason for reason in PlanRouteReason if reason.name.startswith("PHASE_NOT_")
    )


_PHASE_ROWS = _phase_rows()


@pytest.mark.parametrize("reason", _PHASE_ROWS, ids=[r.name for r in _PHASE_ROWS])
def test_a_phase_row_says_outside_the_bound_or_is_a_named_exception(reason) -> None:
    """``ROLE_PHASE_FORBIDDEN`` claims the CATALOGUE forbids the role.

    A phase that is not the canary's says nothing about the role, so the two
    cannot share a code — B5's bar is read from these counters and "one code
    cannot say two things" is the rule every neighbouring docstring states.
    #11543 migrated the REVIEW row and left PLAN and IMPLEMENT to their
    owners; before #11716 that exception lived only in a comment beside the
    rows, and flipping either survived the suite in both directions.
    """
    from driver_contracts import RejectionReason
    from plan_broker import PHASE_ROWS_STILL_CONFLATED, REFUSAL_CODES

    code = REFUSAL_CODES[reason]
    if reason.name in PHASE_ROWS_STILL_CONFLATED:
        assert code is RejectionReason.ROLE_PHASE_FORBIDDEN, (
            f"{reason.name} is recorded as a known conflation but no longer "
            "reports ROLE_PHASE_FORBIDDEN. Drop it from "
            "plan_broker.PHASE_ROWS_STILL_CONFLATED — the set is shrink-only "
            "and this is the shrink."
        )
    else:
        assert code is RejectionReason.OUTSIDE_CANARY_BOUND, (
            f"{reason.name} reports {code.value!r}. A phase outside the "
            "canary's bound is OUTSIDE_CANARY_BOUND; ROLE_PHASE_FORBIDDEN is "
            "the catalogue's answer about a ROLE. If this row is a deliberate "
            "exception, name it in plan_broker.PHASE_ROWS_STILL_CONFLATED so "
            "a reader can tell it from an unfinished migration."
        )


def test_the_conflation_exception_names_only_live_rows() -> None:
    """A shrink-only set of dead names exempts nothing and reads as progress.

    The #11669 class applied to an exception list: an entry naming a member
    that no longer exists looks exactly like an entry doing work.
    """
    from plan_broker import PHASE_ROWS_STILL_CONFLATED

    live = {reason.name for reason in _PHASE_ROWS}

    assert _PHASE_ROWS, "no PHASE_NOT_* members — the derivation lost its subject"
    assert live >= PHASE_ROWS_STILL_CONFLATED, sorted(PHASE_ROWS_STILL_CONFLATED - live)


#: Shrink-only. Lower it when a phase migrates its row; never raise it.
CONFLATED_PHASE_ROWS_MAX = 2


def test_the_conflation_exception_only_shrinks() -> None:
    from plan_broker import PHASE_ROWS_STILL_CONFLATED

    assert len(PHASE_ROWS_STILL_CONFLATED) <= CONFLATED_PHASE_ROWS_MAX, (
        f"{sorted(PHASE_ROWS_STILL_CONFLATED)} still conflate 'the phase is "
        "not the canary's' with 'the catalogue forbids this role'. A new "
        "canary must not add a third."
    )

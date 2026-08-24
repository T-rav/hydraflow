"""Admission for the Fable REVIEW canary (ADR-0137 P5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig
from driver_contracts import (
    WORKER_CATALOG,
    DriverPhase,
    RejectionReason,
    WorkerRole,
    WriteScope,
)
from implement_broker import implement_canary_covers
from plan_broker import plan_canary_covers
from review_broker import (
    CANARY_PHASE,
    review_canary_armed,
    review_canary_covers,
    review_canary_repo,
    review_roles_for_review_phase,
    reviewer_independence_refusal,
)


def _config(**kwargs: object) -> HydraFlowConfig:
    return HydraFlowConfig(**kwargs)  # type: ignore[arg-type]


def test_the_dial_is_empty_by_default_so_nothing_dispatches() -> None:
    """The off-switch is the default, not a thing an operator must set."""
    config = _config()
    assert config.fable_review_canary_repo == ""
    assert review_canary_repo(config) is None
    assert review_canary_armed(config) is False


def test_arming_review_does_not_arm_plan_or_implement() -> None:
    """Three dials, three decisions. One dial would mean an operator running
    the Plan canary today woke up dispatching reviewers tomorrow.

    Asserted through the sibling PREDICATES, not through their dials' default
    values. The earlier version read ``config.fable_plan_canary_repo == ""``,
    which is a fact about a default and would have passed unchanged if
    ``plan_canary_covers`` had been wired to read the *review* dial — the one
    failure the test exists to catch.
    """
    config = _config(fable_review_canary_repo="acme/widget", repo="acme/widget")
    assert review_canary_covers(config, phase=DriverPhase.REVIEW) is True
    assert plan_canary_covers(config, phase=DriverPhase.PLAN) is False
    assert implement_canary_covers(config, phase=DriverPhase.IMPLEMENT) is False


def test_arming_plan_or_implement_does_not_arm_review() -> None:
    """The property in the other direction — the one #11541/#11542 promised."""
    for dial in ("fable_plan_canary_repo", "fable_implement_canary_repo"):
        config = _config(**{dial: "acme/widget", "repo": "acme/widget"})
        assert review_canary_armed(config) is False, dial
        assert review_canary_covers(config, phase=DriverPhase.REVIEW) is False, dial


def test_the_bound_is_one_exact_repository() -> None:
    config = _config(fable_review_canary_repo="acme/widget", repo="acme/widget")
    assert review_canary_covers(config, phase=DriverPhase.REVIEW) is True

    other = _config(fable_review_canary_repo="acme/widget", repo="acme/other")
    assert review_canary_covers(other, phase=DriverPhase.REVIEW) is False


def test_a_lossy_slug_is_refused_before_it_can_be_compared() -> None:
    """Stronger than a non-match: config will not hold one.

    The bound is an exact canonical identity, so a value that cannot BE one is
    rejected at construction rather than silently failing to match later. A
    near-miss that merely fails the comparison would be indistinguishable from
    a correctly-unarmed canary in a log.
    """
    with pytest.raises(ValidationError, match="expected 'owner/repo'"):
        _config(fable_review_canary_repo="acme/widget", repo="widget")


@pytest.mark.parametrize(
    "dial",
    [
        "fable_plan_canary_repo",
        "fable_implement_canary_repo",
        "fable_review_canary_repo",
    ],
)
def test_a_typo_in_any_canary_dial_fails_loudly(dial: str) -> None:
    """A dial that can arm nothing must say so at load, not at the spawn.

    The review dial joins the EXISTING ``_FABLE_CANARY_DIALS`` tuple rather
    than getting a validator of its own: two validators over one vocabulary is
    how they drift, and the second one silently changed the error message the
    plan and implement tests pin.
    """
    for dialled in ("acme/widgets/extra", "no-slash", "acme-widgets"):
        with pytest.raises(ValidationError, match="canonical"):
            _config(**{dial: dialled})


@pytest.mark.parametrize(
    "dial",
    [
        "fable_plan_canary_repo",
        "fable_implement_canary_repo",
        "fable_review_canary_repo",
    ],
)
def test_empty_stays_valid_because_empty_is_the_off_switch(dial: str) -> None:
    assert getattr(_config(**{dial: ""}), dial) == ""


def test_a_different_owner_does_not_match() -> None:
    """Both halves of the identity are compared, not just the repo name."""
    config = _config(fable_review_canary_repo="acme/widget", repo="other/widget")
    assert review_canary_covers(config, phase=DriverPhase.REVIEW) is False


@pytest.mark.parametrize(
    "phase",
    [DriverPhase.PLAN, DriverPhase.IMPLEMENT, None],
)
def test_only_the_review_phase_is_covered(phase: DriverPhase | None) -> None:
    """Why plan, implement and HITL are unaffected by arming this one."""
    config = _config(fable_review_canary_repo="acme/widget", repo="acme/widget")
    assert review_canary_covers(config, phase=phase) is False


def test_clearing_the_dial_disarms_without_a_restart() -> None:
    """Read per boundary, never captured at construction: a canary switch an
    operator must restart the factory to use is not a canary switch."""
    armed = _config(fable_review_canary_repo="acme/widget", repo="acme/widget")
    assert review_canary_covers(armed, phase=DriverPhase.REVIEW) is True
    cleared = _config(fable_review_canary_repo="", repo="acme/widget")
    assert review_canary_covers(cleared, phase=DriverPhase.REVIEW) is False


def test_the_role_menu_is_derived_from_the_catalogue() -> None:
    """A hardcoded pair would be a second description of the catalogue, free to
    drift from it the day a role is added (#11673's class)."""
    roles = review_roles_for_review_phase()
    assert roles == {
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases and entry.write_scope is WriteScope.NONE
    }
    assert WorkerRole.REVIEWER in roles
    assert WorkerRole.IMPLEMENTER not in roles


def test_the_review_dial_arms_no_writer() -> None:
    """The reason there are three dials, expressed as a property of the menu.

    ``fable_review_canary_repo`` reads as a read-only reviewer canary and an
    operator arms it as one. The catalogue also legalises ``DEBUGGER`` at
    REVIEW, and a debugger holds ``ISSUE_WORKTREE`` — so a menu derived from
    phase alone armed a WRITER at REVIEW without
    ``fable_implement_canary_repo`` being touched, which is precisely the
    "widen one role boundary at a time" rule the three dials exist to keep.
    """
    for role in review_roles_for_review_phase():
        assert WORKER_CATALOG[role].write_scope is WriteScope.NONE, role


def test_the_writer_the_menu_excludes_is_really_catalogued_at_review() -> None:
    """Negative control: without a write-scoped REVIEW role in the catalogue,
    the filter above is a no-op and the test that pins it is vacuous."""
    write_scoped_at_review = {
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases
        and entry.write_scope is not WriteScope.NONE
    }
    assert write_scoped_at_review, "nothing to exclude — the menu filter is vacuous"
    assert not (write_scoped_at_review & review_roles_for_review_phase())


def test_an_implementer_cannot_review_its_own_work() -> None:
    assert (
        reviewer_independence_refusal(
            role=WorkerRole.REVIEWER,
            requesting_spawn_id="spawn-1",
            implementer_spawn_ids=["spawn-1", "spawn-2"],
        )
        is RejectionReason.SELF_REVIEW_FORBIDDEN
    )


def test_a_fresh_reviewer_is_admitted() -> None:
    assert (
        reviewer_independence_refusal(
            role=WorkerRole.REVIEWER,
            requesting_spawn_id="spawn-9",
            implementer_spawn_ids=["spawn-1"],
        )
        is None
    )


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_a_fenced_role_with_no_lineage_is_refused(absent: str | None) -> None:
    """The inversion of what this file used to pin (#11543).

    It asserted that an absent lineage was admissible and called that "intended,
    not an oversight". It was the oversight: nothing in ``src/`` writes
    ``requesting_spawn_id``, so the only request the fence could refuse was one
    where the party being fenced volunteered the value that refused it. A
    latent fail-open pinned as an invariant is worse than an unpinned one — the
    next reader stops looking, and the fix reads as the regression.
    """
    assert (
        reviewer_independence_refusal(
            role=WorkerRole.REVIEWER,
            requesting_spawn_id=absent,
            implementer_spawn_ids=["spawn-1"],
        )
        is RejectionReason.LINEAGE_UNKNOWN
    )


def test_an_unfenced_role_with_no_lineage_is_still_admissible() -> None:
    """The refusal above is about INDEPENDENCE, not about lineage in general.

    A director's own depth-1 explorer legitimately has no parent spawn, and
    refusing it would be the fence spreading past its subject.
    """
    assert (
        reviewer_independence_refusal(
            role=WorkerRole.EXPLORER,
            requesting_spawn_id=None,
            implementer_spawn_ids=["spawn-1"],
        )
        is None
    )


@pytest.mark.parametrize(
    "role",
    sorted(
        (r for r, e in WORKER_CATALOG.items() if not e.independent_of_implementer),
        key=str,
    ),
)
def test_a_role_the_catalogue_does_not_call_independent_is_not_fenced(
    role: WorkerRole,
) -> None:
    """The catalogue decides, not this module."""
    assert (
        reviewer_independence_refusal(
            role=role, requesting_spawn_id="s", implementer_spawn_ids=["s"]
        )
        is None
    )


def test_every_read_only_review_role_is_independent() -> None:
    """Derived, never a role list (#11543).

    Only ``REVIEWER`` carried ``independent_of_implementer``, so an
    implementer's lineage could request ``architect`` or ``test_adequacy`` at
    REVIEW and judge its own work — and a test asserted that hole as correct.
    The rule is a property of the catalogue: a role that reads at REVIEW is
    there to judge, and a judge shares no lineage with what it judges. Hardcode
    the roles and this rots the day one is added.
    """
    read_only_at_review = {
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases and entry.write_scope is WriteScope.NONE
    }
    assert read_only_at_review, "no read-only REVIEW role — the rule has no subject"
    for role in read_only_at_review:
        assert WORKER_CATALOG[role].independent_of_implementer, (
            f"{role} reads at REVIEW but the catalogue does not require it to be "
            "independent of the implementer; it could be requested from the "
            "lineage of the work it is judging."
        )


def test_every_independent_role_is_fenced() -> None:
    """Negative control: the guard above must not be vacuous."""
    independent = [r for r, e in WORKER_CATALOG.items() if e.independent_of_implementer]
    assert independent, "no independent roles — the fence has no subject"
    for role in independent:
        assert (
            reviewer_independence_refusal(
                role=role, requesting_spawn_id="s", implementer_spawn_ids=["s"]
            )
            is RejectionReason.SELF_REVIEW_FORBIDDEN
        )

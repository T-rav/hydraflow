"""Admission for the Fable REVIEW canary (ADR-0137 P5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig
from driver_contracts import WORKER_CATALOG, DriverPhase, RejectionReason, WorkerRole
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
    the Plan canary today woke up dispatching reviewers tomorrow."""
    config = _config(fable_review_canary_repo="acme/widget")
    assert review_canary_armed(config) is True
    assert config.fable_plan_canary_repo == ""
    assert config.fable_implement_canary_repo == ""


def test_arming_plan_or_implement_does_not_arm_review() -> None:
    """The property in the other direction — the one #11541/#11542 promised."""
    for dial in ("fable_plan_canary_repo", "fable_implement_canary_repo"):
        config = _config(**{dial: "acme/widget"})
        assert review_canary_armed(config) is False, dial


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
        if CANARY_PHASE in entry.allowed_phases
    }
    assert WorkerRole.REVIEWER in roles
    assert WorkerRole.IMPLEMENTER not in roles


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


def test_a_request_with_no_parent_spawn_is_admissible() -> None:
    """Intended, not an oversight: the fence catches an implementer reviewing
    itself, and a request with no implementer lineage is not that."""
    assert (
        reviewer_independence_refusal(
            role=WorkerRole.REVIEWER,
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


# ---------------------------------------------------------------------------
# The REVIEW binding of the one shared tier resolver (#11543)
# ---------------------------------------------------------------------------


def _review_request(
    *, role: WorkerRole = WorkerRole.REVIEWER, value: str = "claude-opus"
):
    from driver_contracts import (
        ModelRequirement,
        ModelRequirementKind,
        WorkerDispatchRequest,
    )

    return WorkerDispatchRequest(
        request_id="req-1",
        driver_id="drv-1",
        epoch=1,
        phase_attempt=1,
        worker_role=role,
        model_requirement=ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value=value
        ),
        task_contract="review the change",
        reason="the implement boundary finished",
        expected_route_policy_revision="route-v1",
        idempotency_key="key-1",
    )


def test_a_catalogued_reviewer_resolves_to_the_catalogued_opus_id() -> None:
    """The tier tables are shared with PLAN and IMPLEMENT, deliberately: a
    third copy would carry a third answer to "which id is claude-opus", and
    this is the phase where a canary that quietly reviewed with Sonnet would
    still look armed."""
    from plan_broker import PLAN_TIER_CATALOG, PlanRouteOutcome
    from review_broker import resolve_review_model

    decision = resolve_review_model(
        _review_request(), phase=DriverPhase.REVIEW, route_policy_revision="route-v1"
    )

    assert decision.outcome is PlanRouteOutcome.SELECTED
    assert decision.served_model == PLAN_TIER_CATALOG["claude-opus"]


def test_a_non_review_boundary_is_refused_in_its_own_words() -> None:
    from plan_broker import PlanRouteOutcome, PlanRouteReason
    from review_broker import resolve_review_model

    decision = resolve_review_model(
        _review_request(), phase=DriverPhase.PLAN, route_policy_revision="route-v1"
    )

    assert decision.outcome is PlanRouteOutcome.REJECTED
    assert decision.reason is PlanRouteReason.PHASE_NOT_REVIEW


def test_a_role_not_catalogued_for_review_is_refused_in_its_own_words() -> None:
    from plan_broker import PlanRouteOutcome, PlanRouteReason
    from review_broker import resolve_review_model

    assert DriverPhase.REVIEW not in WORKER_CATALOG[WorkerRole.PLANNER].allowed_phases
    decision = resolve_review_model(
        _review_request(role=WorkerRole.PLANNER, value="claude-sonnet"),
        phase=DriverPhase.REVIEW,
        route_policy_revision="route-v1",
    )

    assert decision.outcome is PlanRouteOutcome.REJECTED
    assert decision.reason is PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_REVIEW


def test_every_review_refusal_reason_has_a_receipt_code() -> None:
    """The one vocabulary stays total. #11670 paid for a second, divergent
    table with two invented members and two real ones missing, both of which
    degraded to *retryable*."""
    from plan_broker import REFUSAL_CODES, PlanRouteReason

    assert PlanRouteReason.PHASE_NOT_REVIEW in REFUSAL_CODES
    assert PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_REVIEW in REFUSAL_CODES
    assert set(REFUSAL_CODES) == set(PlanRouteReason) - {PlanRouteReason.NONE}


@pytest.mark.parametrize(
    "dial",
    [
        pytest.param("fable_review_canary_repo", id="repository"),
        pytest.param("fable_review_worker_timeout_seconds", id="budget"),
    ],
)
def test_both_review_dials_are_live_and_not_environment_overridable(dial: str) -> None:
    """ADR-0141 D5's lesson inherited rather than relearned for a third time.
    The rollback depends on liveness: an actuator already constructed keeps
    existing, and what stops it dispatching is the predicate being re-read. An
    env override applies whenever a field is at its *default*, and for the
    repository dial the disarmed value IS the default."""
    from config import _ENV_INT_OVERRIDES, _ENV_STR_OVERRIDES
    from settings_registry import SETTINGS

    assert SETTINGS[dial].live is True
    rows = [*_ENV_STR_OVERRIDES, *_ENV_INT_OVERRIDES]
    assert [row for row in rows if row[0] == dial] == []

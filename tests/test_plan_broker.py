"""The brokered Plan canary's decision layer (#11541).

Three separable claims live in :mod:`plan_broker`, and each has its own class
below:

* **the bound** — a boundary is inside the canary only when the dial names this
  exact repository *and* the phase is PLAN. Nothing widens it, and clearing the
  dial closes it on the next boundary;
* **the tier choice** — a requirement plus a role resolves to exactly one
  concrete Anthropic model id, deterministically, with a decision record that
  explains itself after the fact;
* **the latch** — at most one issue per repository holds the brokered-Plan slot.

Everything here is pure: no config object is mutated, no process is spawned, no
file is written. The dispatch half is ``tests/test_plan_worker_runner.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from driver_contracts import (
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    WorkerDispatchRequest,
    WorkerRole,
    has_anthropic_provenance,
)
from plan_broker import (
    PLAN_TIER_CATALOG,
    PLAN_TIER_CATALOG_REVISION,
    PlanCanaryLatch,
    PlanRouteOutcome,
    PlanRouteReason,
    PlanRouteRule,
    PlanRouteSource,
    plan_canary_covers,
    plan_canary_repo,
    plan_roles_for_plan_phase,
    resolve_plan_model,
)

ROUTE_REVISION = "route-test-1"


def _request(
    *,
    role: WorkerRole = WorkerRole.PLANNER,
    kind: ModelRequirementKind = ModelRequirementKind.LITERAL_FAMILY,
    value: str = "claude-sonnet",
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id=f"req-{role.value}",
        driver_id="drv-1",
        epoch=0,
        phase_attempt=0,
        worker_role=role,
        model_requirement=ModelRequirement(kind=kind, value=value),
        task_contract="do the thing",
        reason="because",
        expected_route_policy_revision=ROUTE_REVISION,
        idempotency_key=f"key-{role.value}",
    )


def _resolve(request: WorkerDispatchRequest, **kwargs: object):
    defaults: dict[str, object] = {
        "phase": DriverPhase.PLAN,
        "route_policy_revision": ROUTE_REVISION,
        "lane_serves_anthropic": True,
    }
    defaults.update(kwargs)
    return resolve_plan_model(request, **defaults)  # type: ignore[arg-type]


class _Dialled:
    """The two config reads the bound predicate makes, and nothing else."""

    def __init__(self, *, canary: str, repo: str = "acme/widgets") -> None:
        self.fable_plan_canary_repo = canary
        self.repo = repo


# --------------------------------------------------------------------------
# The bound
# --------------------------------------------------------------------------


class TestTheCanarysBoundIsOneRepositoryAndOnePhase:
    def test_an_empty_dial_covers_nothing(self) -> None:
        assert plan_canary_covers(_Dialled(canary=""), phase=DriverPhase.PLAN) is False

    def test_the_named_repository_at_plan_is_covered(self) -> None:
        assert (
            plan_canary_covers(_Dialled(canary="acme/widgets"), phase=DriverPhase.PLAN)
            is True
        )

    @pytest.mark.parametrize(
        "phase",
        [
            pytest.param(DriverPhase.TRIAGE, id="triage"),
            pytest.param(DriverPhase.IMPLEMENT, id="implement"),
            pytest.param(DriverPhase.REVIEW, id="review"),
            pytest.param(DriverPhase.HITL, id="hitl"),
        ],
    )
    def test_every_other_phase_is_outside_the_bound(self, phase: DriverPhase) -> None:
        # "Implement, review, and HITL remain Classic" is a property of this
        # predicate, not of a caller remembering to check the phase.
        assert plan_canary_covers(_Dialled(canary="acme/widgets"), phase=phase) is False

    def test_another_repository_is_outside_the_bound(self) -> None:
        dialled = _Dialled(canary="acme/other", repo="acme/widgets")

        assert plan_canary_covers(dialled, phase=DriverPhase.PLAN) is False

    @pytest.mark.parametrize(
        "dialled",
        [
            pytest.param("acme-widgets", id="runtime-slug"),
            pytest.param("widgets", id="bare-name"),
            pytest.param("https://github.com/acme/widgets", id="url"),
            pytest.param("   ", id="whitespace"),
        ],
    )
    def test_a_non_canonical_dial_arms_nothing(self, dialled: str) -> None:
        # ADR-0139 D2's lossy-slug refusal, reused: an identity that is not
        # exactly ``owner/repo`` can never match in either direction.
        assert plan_canary_repo(_Dialled(canary=dialled)) is None

    def test_the_plan_roles_come_from_the_catalog_not_a_second_list(self) -> None:
        # A hardcoded list here would be a second copy of the catalog, and the
        # two would drift the moment a role's allowed_phases changed.
        assert plan_roles_for_plan_phase() == frozenset(
            {WorkerRole.EXPLORER, WorkerRole.PLANNER, WorkerRole.ARCHITECT}
        )


# --------------------------------------------------------------------------
# The tier choice
# --------------------------------------------------------------------------


class TestTheBrokerChoosesBetweenSonnetAndOpus:
    @pytest.mark.parametrize(
        ("role", "family", "token"),
        [
            pytest.param(WorkerRole.PLANNER, "claude-sonnet", "sonnet", id="planner"),
            pytest.param(WorkerRole.EXPLORER, "claude-sonnet", "sonnet", id="explorer"),
            pytest.param(WorkerRole.ARCHITECT, "claude-opus", "opus", id="architect"),
        ],
    )
    def test_a_literal_family_resolves_to_a_model_of_that_family(
        self, role: WorkerRole, family: str, token: str
    ) -> None:
        decision = _resolve(_request(role=role, value=family))

        assert decision.outcome is PlanRouteOutcome.SELECTED
        assert token in decision.served_model

    def test_every_catalogued_tier_has_anthropic_provenance(self) -> None:
        # The "never substitutes GLM" invariant, stated against the table
        # rather than against one resolution: an edit that put ``glm-5.3``
        # under ``claude-opus`` would pass every behavioural test above.
        assert all(
            has_anthropic_provenance(model) for model in PLAN_TIER_CATALOG.values()
        )

    def test_every_catalogued_tier_satisfies_its_own_family(self) -> None:
        assert all(
            ModelRequirement(
                kind=ModelRequirementKind.LITERAL_FAMILY, value=family
            ).satisfied_by(model)
            for family, model in PLAN_TIER_CATALOG.items()
        )

    @pytest.mark.parametrize(
        ("capability", "token"),
        [
            pytest.param("high-reasoning", "opus", id="high-reasoning"),
            pytest.param("balanced", "sonnet", id="balanced"),
        ],
    )
    def test_a_capability_class_resolves_through_the_tier_table(
        self, capability: str, token: str
    ) -> None:
        decision = _resolve(
            _request(
                role=WorkerRole.ARCHITECT,
                kind=ModelRequirementKind.CAPABILITY,
                value=capability,
            )
        )

        assert decision.outcome is PlanRouteOutcome.SELECTED
        assert token in decision.served_model

    def test_the_same_input_always_produces_the_same_decision_id(self) -> None:
        first = _resolve(_request())
        second = _resolve(_request())

        assert first.decision_id == second.decision_id

    def test_a_different_input_produces_a_different_decision_id(self) -> None:
        sonnet = _resolve(_request(role=WorkerRole.PLANNER, value="claude-sonnet"))
        opus = _resolve(_request(role=WorkerRole.ARCHITECT, value="claude-opus"))

        assert sonnet.decision_id != opus.decision_id


class TestTheDecisionExplainsItselfAfterTheFact:
    def test_a_literal_request_records_the_director_as_the_source(self) -> None:
        decision = _resolve(_request())

        assert decision.source is PlanRouteSource.DIRECTOR_LITERAL

    def test_a_capability_request_records_the_tier_table_as_the_source(self) -> None:
        decision = _resolve(
            _request(kind=ModelRequirementKind.CAPABILITY, value="balanced")
        )

        assert decision.source is PlanRouteSource.CAPABILITY_TABLE

    def test_the_matched_rule_is_named(self) -> None:
        decision = _resolve(_request())

        assert decision.rule is PlanRouteRule.LITERAL_FAMILY_TO_CATALOGUED_ID

    def test_the_catalogue_revision_travels_on_the_decision(self) -> None:
        # The gateway resolver's standard: a decision that cannot name the
        # revision it was made against cannot be replayed against it.
        decision = _resolve(_request())

        assert decision.catalog_revision == PLAN_TIER_CATALOG_REVISION

    def test_the_route_policy_revision_travels_on_the_decision(self) -> None:
        decision = _resolve(_request(), route_policy_revision="route-other")

        assert decision.route_policy_revision == "route-other"

    def test_the_input_context_is_echoed_back(self) -> None:
        decision = _resolve(_request(role=WorkerRole.ARCHITECT, value="claude-opus"))

        assert (
            decision.worker_role,
            decision.phase,
            decision.requirement_kind,
            decision.requirement_value,
        ) == ("architect", "PLAN", "literal_family", "claude-opus")

    def test_explain_carries_every_field_the_receipt_joins_on(self) -> None:
        explained = _resolve(_request()).explain()

        assert set(explained) >= {
            "decision_id",
            "outcome",
            "rule",
            "source",
            "reason",
            "catalog_revision",
            "route_policy_revision",
            "worker_role",
            "phase",
            "requirement_kind",
            "requirement_value",
            "served_model",
        }


class TestALiteralFamilyHoldsOrRejectsRatherThanSubstituting:
    def test_a_lane_that_cannot_serve_anthropic_rejects_a_literal_family(self) -> None:
        # The z.ai-locked repository. "Resolve literally or hold/reject; never
        # substitute GLM" — asserted on the outcome, not on the served model,
        # because a served model of "" proves nothing on its own.
        decision = _resolve(_request(), lane_serves_anthropic=False)

        assert decision.outcome is PlanRouteOutcome.REJECTED
        assert decision.reason is PlanRouteReason.LITERAL_FAMILY_UNSATISFIABLE

    def test_a_rejected_decision_names_no_served_model(self) -> None:
        decision = _resolve(_request(), lane_serves_anthropic=False)

        assert decision.served_model == ""

    def test_a_capability_class_also_rejects_on_a_non_anthropic_lane(self) -> None:
        # The tier table answers a capability with an Anthropic model, so a
        # lane that cannot serve one cannot serve this either. Letting the
        # capability arm through would be the substitution path reopened one
        # requirement kind over.
        decision = _resolve(
            _request(kind=ModelRequirementKind.CAPABILITY, value="balanced"),
            lane_serves_anthropic=False,
        )

        assert decision.outcome is PlanRouteOutcome.REJECTED

    def test_a_role_not_catalogued_for_plan_is_rejected(self) -> None:
        decision = _resolve(_request(role=WorkerRole.IMPLEMENTER))

        assert decision.reason is PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_PLAN

    @pytest.mark.parametrize(
        "phase",
        [
            pytest.param(DriverPhase.IMPLEMENT, id="implement"),
            pytest.param(DriverPhase.REVIEW, id="review"),
            pytest.param(DriverPhase.HITL, id="hitl"),
        ],
    )
    def test_any_phase_but_plan_is_rejected(self, phase: DriverPhase) -> None:
        decision = _resolve(_request(), phase=phase)

        assert decision.reason is PlanRouteReason.PHASE_NOT_PLAN


# --------------------------------------------------------------------------
# The latch
# --------------------------------------------------------------------------


class TestOneActiveFableDirectedIssuePerRepository:
    def test_the_first_issue_claims_the_slot(self) -> None:
        latch = PlanCanaryLatch(ttl_seconds=900)

        assert latch.claim(101, now=datetime.now(UTC)) is True

    def test_a_second_issue_is_refused_while_the_first_holds_it(self) -> None:
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)

        assert latch.claim(202, now=now) is False

    def test_the_holder_may_reclaim_its_own_slot(self) -> None:
        # A driver reaching a second PLAN boundary for the same issue is the
        # same logical Fable session, not a second one.
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)

        assert latch.claim(101, now=now) is True

    def test_releasing_frees_the_slot(self) -> None:
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)
        latch.release(101)

        assert latch.claim(202, now=now) is True

    def test_releasing_a_slot_someone_else_holds_does_nothing(self) -> None:
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)
        latch.release(202)

        assert latch.holder == 101

    def test_an_abandoned_hold_expires_rather_than_wedging_the_canary(self) -> None:
        # A crash between claim and release must not take the canary out of
        # service until someone restarts the factory.
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)

        assert latch.claim(202, now=now + timedelta(seconds=901)) is True

    def test_a_live_hold_does_not_expire_early(self) -> None:
        latch = PlanCanaryLatch(ttl_seconds=900)
        now = datetime.now(UTC)
        latch.claim(101, now=now)

        assert latch.claim(202, now=now + timedelta(seconds=899)) is False

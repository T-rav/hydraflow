"""Contract tests for the fixed IssueDriver / director contracts (ADR-0137, #11533)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from driver_contracts import (
    MAX_CAPSULE_RECEIPTS,
    MAX_DISPATCH_BATCH,
    WORKER_CATALOG,
    DirectorCapsule,
    DirectorCommand,
    DirectorCommandKind,
    DriverCheckpoint,
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    ReceiptStatus,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerLineage,
    WorkerReceipt,
    WorkerRole,
    WriterLease,
    WriteScope,
    admit_dispatch,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _lease(**overrides: object) -> DriverLease:
    base: dict[str, object] = {
        "driver_id": "drv-1",
        "epoch": 3,
        "repo_slug": "T-rav/hydraflow",
        "issue_number": 11533,
        "phase": DriverPhase.PLAN,
        "expected_stage_label": "hydraflow-plan",
        "phase_attempt": 1,
        "expires_at": NOW + timedelta(minutes=30),
    }
    base.update(overrides)
    return DriverLease(**base)  # type: ignore[arg-type]


def _request(**overrides: object) -> WorkerDispatchRequest:
    base: dict[str, object] = {
        "request_id": "req-1",
        "driver_id": "drv-1",
        "epoch": 3,
        "phase_attempt": 1,
        "worker_role": WorkerRole.PLANNER,
        "model_requirement": ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
        ),
        "task_contract": "draft the plan",
        "reason": "plan phase needs a draft",
        "expected_route_policy_revision": "rev-7",
        "idempotency_key": "idem-1",
    }
    base.update(overrides)
    return WorkerDispatchRequest(**base)  # type: ignore[arg-type]


def _writer_lease(**overrides: object) -> WriterLease:
    base: dict[str, object] = {
        "driver_id": "drv-1",
        "epoch": 3,
        "worktree_base_digest": "base-abc",
        "worktree_head_digest": "head-def",
    }
    base.update(overrides)
    return WriterLease(**base)  # type: ignore[arg-type]


def _admit(**overrides: object) -> RejectionReason | None:
    kwargs: dict[str, object] = {
        "lease": _lease(),
        "now": NOW,
        "live_stage_label": "hydraflow-plan",
        "route_policy_revision": "rev-7",
        "writer_lease": _writer_lease(),
        "remaining_usd_budget": 5.0,
    }
    request = overrides.pop("request", _request())
    kwargs.update(overrides)
    return admit_dispatch(request, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# ModelRequirement — the "GLM is never reported as Sonnet" invariant
# --------------------------------------------------------------------------


def test_literal_family_rejects_a_value_outside_the_two_anthropic_families() -> None:
    with pytest.raises(ValidationError):
        ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value="glm-5.3")


def test_capability_rejects_a_value_outside_the_two_neutral_classes() -> None:
    with pytest.raises(ValidationError):
        ModelRequirement(kind=ModelRequirementKind.CAPABILITY, value="cheapest")


def test_literal_sonnet_is_not_satisfied_by_a_glm_model() -> None:
    requirement = ModelRequirement(
        kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
    )

    assert requirement.satisfied_by("glm-5.3-sonnet-compat") is False


def test_literal_sonnet_is_satisfied_by_an_actual_sonnet_model() -> None:
    requirement = ModelRequirement(
        kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
    )

    assert requirement.satisfied_by("claude-sonnet-4-6") is True


def test_literal_opus_is_not_satisfied_by_a_sonnet_model() -> None:
    requirement = ModelRequirement(
        kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-opus"
    )

    assert requirement.satisfied_by("claude-sonnet-4-6") is False


def test_capability_class_is_satisfied_by_any_approved_backend() -> None:
    requirement = ModelRequirement(
        kind=ModelRequirementKind.CAPABILITY, value="high-reasoning"
    )

    assert requirement.satisfied_by("glm-5.3") is True


# --------------------------------------------------------------------------
# Frozen / extra=forbid / round-trip
# --------------------------------------------------------------------------


def test_dispatch_request_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        _request(smuggled_credential="sk-live")


def test_lease_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        _lease(bearer_token="hf-control")


def test_dispatch_request_round_trips_through_json() -> None:
    request = _request()

    assert (
        WorkerDispatchRequest.model_validate_json(request.model_dump_json()) == request
    )


def test_checkpoint_round_trips_through_json() -> None:
    checkpoint = DriverCheckpoint(
        driver_id="drv-1",
        epoch=3,
        last_committed_phase=DriverPhase.REVIEW,
        committed_stage_label="hydraflow-review",
        capsule_digest="cap-123",
        vendor_session_id="vendor-abc",
    )

    assert (
        DriverCheckpoint.model_validate_json(checkpoint.model_dump_json()) == checkpoint
    )


def test_lease_is_frozen_against_direct_mutation() -> None:
    lease = _lease()

    with pytest.raises(ValidationError):
        lease.epoch = 99  # type: ignore[misc]


# --------------------------------------------------------------------------
# DriverLease — expiry is an admission concern, not a construction concern
# --------------------------------------------------------------------------


def test_an_already_expired_lease_still_constructs_for_audit_replay() -> None:
    lease = _lease(expires_at=NOW - timedelta(hours=1))

    assert lease.is_expired(NOW) is True


def test_a_live_lease_reports_unexpired() -> None:
    assert _lease().is_expired(NOW) is False


# --------------------------------------------------------------------------
# DirectorCommand — the only actionable surface
# --------------------------------------------------------------------------


def test_dispatch_command_rejects_an_empty_batch() -> None:
    with pytest.raises(ValidationError):
        DirectorCommand(kind=DirectorCommandKind.DISPATCH_WORKERS, dispatches=())


def test_dispatch_command_rejects_a_batch_over_the_fanout_ceiling() -> None:
    oversized = tuple(
        _request(request_id=f"req-{i}", idempotency_key=f"idem-{i}")
        for i in range(MAX_DISPATCH_BATCH + 1)
    )

    with pytest.raises(ValidationError):
        DirectorCommand(kind=DirectorCommandKind.DISPATCH_WORKERS, dispatches=oversized)


def test_dispatch_command_rejects_a_duplicate_idempotency_key_within_one_batch() -> (
    None
):
    twins = (_request(request_id="req-a"), _request(request_id="req-b"))

    with pytest.raises(ValidationError):
        DirectorCommand(kind=DirectorCommandKind.DISPATCH_WORKERS, dispatches=twins)


def test_yield_command_rejects_carrying_dispatches() -> None:
    with pytest.raises(ValidationError):
        DirectorCommand(kind=DirectorCommandKind.YIELD, dispatches=(_request(),))


def test_finish_command_is_valid_with_no_dispatches() -> None:
    command = DirectorCommand(kind=DirectorCommandKind.FINISH)

    assert command.dispatches == ()


# --------------------------------------------------------------------------
# DirectorCapsule — bounded, catalogued, no ambient secrets
# --------------------------------------------------------------------------


def _capsule(**overrides: object) -> DirectorCapsule:
    base: dict[str, object] = {
        "lease": _lease(),
        "issue_goal": "resolve the architecture conflict",
        "live_stage_label": "hydraflow-plan",
        "route_policy_revision": "rev-7",
        "remaining_usd_budget": 5.0,
        "remaining_wall_clock_seconds": 1800,
    }
    base.update(overrides)
    return DirectorCapsule(**base)  # type: ignore[arg-type]


def test_capsule_rejects_a_role_absent_from_the_catalog() -> None:
    with pytest.raises(ValidationError):
        DirectorCapsule(
            lease=_lease(),
            issue_goal="g",
            live_stage_label="hydraflow-plan",
            route_policy_revision="rev-7",
            remaining_usd_budget=1.0,
            remaining_wall_clock_seconds=60,
            allowed_roles=frozenset({"ghost_role"}),  # type: ignore[arg-type]
        )


def test_capsule_rejects_more_prior_receipts_than_the_bound() -> None:
    receipt = WorkerReceipt(
        request_id="r",
        idempotency_key="i",
        status=ReceiptStatus.REJECTED,
        reason_code=RejectionReason.STOP_FENCE,
        worker_role=WorkerRole.PLANNER,
        requested_model=ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
        ),
        route_policy_revision="rev-7",
    )

    with pytest.raises(ValidationError):
        _capsule(prior_receipts=tuple([receipt] * (MAX_CAPSULE_RECEIPTS + 1)))


def test_capsule_rejects_an_unknown_field_so_secrets_cannot_ride_along() -> None:
    with pytest.raises(ValidationError):
        _capsule(anthropic_api_key="sk-live")


# --------------------------------------------------------------------------
# WorkerReceipt — deterministic reasons, lineage, honest model reporting
# --------------------------------------------------------------------------


def _accepted_receipt(**overrides: object) -> WorkerReceipt:
    base: dict[str, object] = {
        "request_id": "req-1",
        "idempotency_key": "idem-1",
        "status": ReceiptStatus.ACCEPTED,
        "lineage": WorkerLineage(
            driver_id="drv-1", epoch=3, child_spawn_id="c1", depth=1
        ),
        "worker_role": WorkerRole.PLANNER,
        "requested_model": ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
        ),
        "served_model": "claude-sonnet-4-6",
        "route_policy_revision": "rev-7",
    }
    base.update(overrides)
    return WorkerReceipt(**base)  # type: ignore[arg-type]


def test_accepted_receipt_rejects_a_glm_model_served_against_a_literal_sonnet_request() -> (
    None
):
    with pytest.raises(ValidationError):
        _accepted_receipt(served_model="glm-5.3")


def test_accepted_receipt_requires_lineage() -> None:
    with pytest.raises(ValidationError):
        _accepted_receipt(lineage=None)


def test_accepted_receipt_requires_the_served_model_to_be_recorded() -> None:
    with pytest.raises(ValidationError):
        _accepted_receipt(served_model=None)


def test_rejected_receipt_requires_a_deterministic_reason_code() -> None:
    with pytest.raises(ValidationError):
        WorkerReceipt(
            request_id="req-1",
            idempotency_key="idem-1",
            status=ReceiptStatus.REJECTED,
            worker_role=WorkerRole.PLANNER,
            requested_model=ModelRequirement(
                kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
            ),
            route_policy_revision="rev-7",
        )


def test_accepted_receipt_rejects_carrying_a_rejection_reason() -> None:
    with pytest.raises(ValidationError):
        _accepted_receipt(reason_code=RejectionReason.STOP_FENCE)


def test_lineage_depth_is_capped_at_two() -> None:
    with pytest.raises(ValidationError):
        WorkerLineage(driver_id="drv-1", epoch=3, child_spawn_id="c1", depth=3)


# --------------------------------------------------------------------------
# Worker catalog
# --------------------------------------------------------------------------


def test_catalog_enumerates_exactly_the_seven_proposal_roles() -> None:
    assert set(WORKER_CATALOG) == set(WorkerRole)


def test_reviewer_is_marked_independent_of_the_implementer() -> None:
    assert WORKER_CATALOG[WorkerRole.REVIEWER].independent_of_implementer is True


def test_reviewer_never_holds_worktree_write_scope() -> None:
    assert (
        WORKER_CATALOG[WorkerRole.REVIEWER].write_scope is not WriteScope.ISSUE_WORKTREE
    )


def test_explorer_is_read_only() -> None:
    assert (
        WORKER_CATALOG[WorkerRole.EXPLORER].write_scope is WriteScope.READ_ONLY_SNAPSHOT
    )


def test_no_catalog_role_is_allowed_in_a_phase_outside_the_live_topology() -> None:
    allowed = {phase for e in WORKER_CATALOG.values() for phase in e.allowed_phases}

    assert allowed <= set(DriverPhase)


# --------------------------------------------------------------------------
# admit_dispatch — the pure, deterministic admission engine
# --------------------------------------------------------------------------


def test_a_clean_request_is_admitted() -> None:
    assert _admit() is None


def test_stop_fence_beats_every_other_reason() -> None:
    assert _admit(stop_requested=True, draining=True) is RejectionReason.STOP_FENCE


def test_draining_is_rejected() -> None:
    assert _admit(draining=True) is RejectionReason.DRAINING


def test_an_unverified_sandbox_is_rejected() -> None:
    assert _admit(sandbox_verified=False) is RejectionReason.SANDBOX_UNVERIFIED


def test_a_stale_epoch_fences_a_late_worker_request() -> None:
    assert _admit(request=_request(epoch=2)) is RejectionReason.STALE_EPOCH


def test_a_stale_phase_attempt_is_rejected() -> None:
    assert (
        _admit(request=_request(phase_attempt=0)) is RejectionReason.STALE_PHASE_ATTEMPT
    )


def test_an_expired_lease_is_rejected_at_admission() -> None:
    assert _admit(now=NOW + timedelta(hours=2)) is RejectionReason.LEASE_EXPIRED


def test_a_live_label_changed_by_a_human_preempts_the_driver() -> None:
    assert (
        _admit(live_stage_label="hydraflow-hitl") is RejectionReason.LIVE_LABEL_CHANGED
    )


def test_a_role_forbidden_in_the_current_phase_is_rejected() -> None:
    reason = _admit(request=_request(worker_role=WorkerRole.REVIEWER))

    assert reason is RejectionReason.ROLE_PHASE_FORBIDDEN


def test_a_stale_route_policy_revision_is_rejected() -> None:
    reason = _admit(request=_request(expected_route_policy_revision="rev-6"))

    assert reason is RejectionReason.ROUTE_POLICY_REVISION_STALE


def test_a_replayed_idempotency_key_is_rejected() -> None:
    reason = _admit(seen_idempotency_keys=frozenset({"idem-1"}))

    assert reason is RejectionReason.DUPLICATE_IDEMPOTENCY_KEY


def test_a_second_writer_is_refused_while_the_writer_lease_is_held() -> None:
    reason = _admit(
        request=_request(worker_role=WorkerRole.IMPLEMENTER, request_id="req-2"),
        lease=_lease(
            phase=DriverPhase.IMPLEMENT, expected_stage_label="hydraflow-ready"
        ),
        live_stage_label="hydraflow-ready",
        writer_lease=_writer_lease(holder_request_id="req-1"),
    )

    assert reason is RejectionReason.WRITER_LEASE_HELD


def test_the_lease_holder_may_continue_writing_in_its_own_worktree() -> None:
    reason = _admit(
        request=_request(worker_role=WorkerRole.IMPLEMENTER, request_id="req-1"),
        lease=_lease(
            phase=DriverPhase.IMPLEMENT, expected_stage_label="hydraflow-ready"
        ),
        live_stage_label="hydraflow-ready",
        writer_lease=_writer_lease(holder_request_id="req-1"),
    )

    assert reason is None


def test_a_reviewer_spawned_inside_the_implementer_lineage_is_refused() -> None:
    reason = _admit(
        request=_request(worker_role=WorkerRole.REVIEWER, request_id="impl-1"),
        lease=_lease(phase=DriverPhase.REVIEW, expected_stage_label="hydraflow-review"),
        live_stage_label="hydraflow-review",
        implementer_spawn_ids=frozenset({"impl-1"}),
    )

    assert reason is RejectionReason.SELF_REVIEW_FORBIDDEN


def test_exceeding_a_role_concurrency_cap_is_rejected() -> None:
    assert _admit(in_flight_for_role=1) is RejectionReason.FANOUT_OVERFLOW


def test_an_exhausted_budget_is_rejected() -> None:
    assert _admit(remaining_usd_budget=0.0) is RejectionReason.BUDGET_EXHAUSTED


def test_ownership_fencing_is_evaluated_before_catalog_legality() -> None:
    # A request that is BOTH stale-epoch and role-phase-illegal reports the
    # ownership failure, so recovery reasons never hide behind catalog noise.
    reason = _admit(request=_request(epoch=2, worker_role=WorkerRole.REVIEWER))

    assert reason is RejectionReason.STALE_EPOCH

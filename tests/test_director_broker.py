"""The narrow deterministic broker: what a director may have, and what it may not.

Two families of assertion live here.

**Admission** — the broker must apply #11533's fixed rule table faithfully and
fold batch state forward correctly. Getting the fold wrong is not a cosmetic
bug: an unfolded idempotency key lets a duplicate through, an unfolded per-role
count lets a fan-out past its cap, and an unfolded writer lease lets two
write-capable children share one worktree.

**Evidence** — a refusal is a real event and gets a real ``WorkerReceipt``; an
admitted request in shadow mode is *not* a real event and must not get one. The
receipt contract exists to make "a GLM model reported as Sonnet" a validation
error, and feeding it a fabricated served model for a worker that never ran
would be the first crack in that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from director_broker import ShadowDispatchBroker
from driver_contracts import (
    DirectorCapsule,
    DirectorCommand,
    DirectorCommandKind,
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    ReceiptStatus,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
    WriterLease,
)

READY_LABEL = "hydraflow-ready"
ROUTE_REVISION = "route-v7"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _lease(
    *, epoch: int = 3, phase: DriverPhase = DriverPhase.IMPLEMENT
) -> DriverLease:
    return DriverLease(
        driver_id="drv-42",
        epoch=epoch,
        repo_slug="acme/widgets",
        issue_number=42,
        phase=phase,
        expected_stage_label=READY_LABEL,
        phase_attempt=0,
        expires_at=NOW + timedelta(hours=1),
    )


def _capsule(
    lease: DriverLease,
    *,
    roles: frozenset[WorkerRole] | None = None,
    budget: float = 5.0,
    stop_requested: bool = False,
    draining: bool = False,
) -> DirectorCapsule:
    return DirectorCapsule(
        lease=lease,
        issue_goal="make the widget work",
        live_stage_label=READY_LABEL,
        allowed_roles=roles
        if roles is not None
        else frozenset(
            {WorkerRole.IMPLEMENTER, WorkerRole.EXPLORER, WorkerRole.DEBUGGER}
        ),
        route_policy_revision=ROUTE_REVISION,
        remaining_usd_budget=budget,
        remaining_wall_clock_seconds=900,
        stop_requested=stop_requested,
        draining=draining,
    )


def _writer_lease(lease: DriverLease) -> WriterLease:
    return WriterLease(
        driver_id=lease.driver_id,
        epoch=lease.epoch,
        holder_request_id=None,
        worktree_base_digest="unobserved",
        worktree_head_digest="unobserved",
    )


def _request(
    *,
    lease: DriverLease,
    role: WorkerRole = WorkerRole.IMPLEMENTER,
    request_id: str = "req-1",
    key: str = "key-1",
    epoch: int | None = None,
    route_revision: str = ROUTE_REVISION,
    family: str = "claude-sonnet",
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id=request_id,
        driver_id=lease.driver_id,
        epoch=lease.epoch if epoch is None else epoch,
        phase_attempt=lease.phase_attempt,
        worker_role=role,
        model_requirement=ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value=family
        ),
        task_contract="implement the fix",
        reason="the issue needs code",
        expected_route_policy_revision=route_revision,
        idempotency_key=key,
    )


def _admit(
    *requests: WorkerDispatchRequest,
    lease: DriverLease,
    capsule: DirectorCapsule | None = None,
    sandbox_verified: bool = True,
    now: datetime = NOW,
):
    command = DirectorCommand(
        kind=DirectorCommandKind.DISPATCH_WORKERS,
        dispatches=tuple(requests),
        rationale="shadow turn",
    )
    return ShadowDispatchBroker().admit(
        command,
        capsule=capsule or _capsule(lease),
        lease=lease,
        writer_lease=_writer_lease(lease),
        sandbox_verified=sandbox_verified,
        now=now,
        live_stage_label=READY_LABEL,
    )


# --------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------


def test_a_catalogued_in_phase_request_would_be_dispatched() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease)

    assert len(verdict.would_dispatch) == 1


def test_a_role_absent_from_the_capsule_is_refused() -> None:
    lease = _lease(phase=DriverPhase.REVIEW)
    capsule = _capsule(lease, roles=frozenset({WorkerRole.ARCHITECT}))

    verdict = _admit(
        _request(lease=lease, role=WorkerRole.REVIEWER), lease=lease, capsule=capsule
    )

    assert verdict.rejection_reasons == (RejectionReason.ROLE_NOT_IN_CAPSULE,)


def test_a_role_the_phase_forbids_is_refused() -> None:
    # A reviewer at IMPLEMENT: catalogued, in the capsule, wrong phase.
    lease = _lease(phase=DriverPhase.IMPLEMENT)
    capsule = _capsule(lease, roles=frozenset({WorkerRole.REVIEWER}))

    verdict = _admit(
        _request(lease=lease, role=WorkerRole.REVIEWER), lease=lease, capsule=capsule
    )

    assert verdict.rejection_reasons == (RejectionReason.ROLE_PHASE_FORBIDDEN,)


def test_a_stale_epoch_is_refused() -> None:
    lease = _lease(epoch=3)

    verdict = _admit(_request(lease=lease, epoch=2), lease=lease)

    assert verdict.rejection_reasons == (RejectionReason.STALE_EPOCH,)


def test_an_unverified_sandbox_refuses_every_dispatch() -> None:
    # S4 is the condition ADR-0137's go depends on, so it fences ahead of
    # everything except stop and drain.
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease, sandbox_verified=False)

    assert verdict.rejection_reasons == (RejectionReason.SANDBOX_UNVERIFIED,)


def test_a_stop_fence_outranks_an_unverified_sandbox() -> None:
    # First-match-wins ordering is the contract; pin that the ordering is the
    # contract's and not one this module reinvented.
    lease = _lease()
    capsule = _capsule(lease, stop_requested=True)

    verdict = _admit(
        _request(lease=lease), lease=lease, capsule=capsule, sandbox_verified=False
    )

    assert verdict.rejection_reasons == (RejectionReason.STOP_FENCE,)


def test_a_stale_route_policy_revision_is_refused() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease, route_revision="route-v6"), lease=lease)

    assert verdict.rejection_reasons == (RejectionReason.ROUTE_POLICY_REVISION_STALE,)


def test_a_stale_route_revision_is_counted_apart_from_other_refusals() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease, route_revision="route-v6"), lease=lease)

    assert verdict.route_revisions == 1


def test_an_exhausted_budget_refuses_every_dispatch() -> None:
    lease = _lease()

    verdict = _admit(
        _request(lease=lease), lease=lease, capsule=_capsule(lease, budget=0.0)
    )

    assert verdict.rejection_reasons == (RejectionReason.BUDGET_EXHAUSTED,)


def test_an_expired_lease_is_refused() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease, now=NOW + timedelta(hours=2))

    assert verdict.rejection_reasons == (RejectionReason.LEASE_EXPIRED,)


# --------------------------------------------------------------------------
# Batch state, folded forward
# --------------------------------------------------------------------------


def test_a_repeated_idempotency_key_within_one_batch_is_refused() -> None:
    # The command validator already rejects duplicate keys, so this arrives via
    # two requests whose keys collide only after the first is admitted — which
    # is exactly what folding forward is for.
    lease = _lease()
    first = _request(lease=lease, request_id="req-1", key="same")
    second = _request(
        lease=lease, request_id="req-2", key="same", role=WorkerRole.EXPLORER
    )

    verdict = ShadowDispatchBroker().admit(
        DirectorCommand.model_construct(
            kind=DirectorCommandKind.DISPATCH_WORKERS,
            dispatches=(first, second),
            rationale="",
            schema_version=1,
        ),
        capsule=_capsule(lease),
        lease=lease,
        writer_lease=_writer_lease(lease),
        sandbox_verified=True,
        now=NOW,
        live_stage_label=READY_LABEL,
    )

    assert verdict.rejection_reasons == (RejectionReason.DUPLICATE_IDEMPOTENCY_KEY,)


def test_a_second_worker_of_a_max_one_role_overflows_the_fan_out() -> None:
    # A read-only role with ``max_concurrency=1``, deliberately: a second
    # *write-capable* worker is refused earlier by the writer lease (below), so
    # using one here would test that rule twice and this one never.
    lease = _lease(phase=DriverPhase.PLAN)
    capsule = _capsule(lease, roles=frozenset({WorkerRole.PLANNER}))
    first = _request(
        lease=lease, request_id="req-1", key="key-1", role=WorkerRole.PLANNER
    )
    second = _request(
        lease=lease, request_id="req-2", key="key-2", role=WorkerRole.PLANNER
    )

    verdict = _admit(first, second, lease=lease, capsule=capsule)

    assert verdict.rejection_reasons == (RejectionReason.FANOUT_OVERFLOW,)


def test_a_second_write_capable_role_cannot_take_the_held_writer_lease() -> None:
    # An implementer and a debugger are different roles — per-role concurrency
    # does not stop them — but they share one worktree. Without folding the
    # writer lease forward, both would be admitted and the single-writer
    # property would hold only across turns, not within one.
    lease = _lease()
    implementer = _request(lease=lease, request_id="req-1", key="key-1")
    debugger = _request(
        lease=lease, request_id="req-2", key="key-2", role=WorkerRole.DEBUGGER
    )

    verdict = _admit(implementer, debugger, lease=lease)

    assert verdict.rejection_reasons == (RejectionReason.WRITER_LEASE_HELD,)


def test_a_read_only_role_is_not_blocked_by_the_writer_lease() -> None:
    lease = _lease()
    implementer = _request(lease=lease, request_id="req-1", key="key-1")
    explorer = _request(
        lease=lease, request_id="req-2", key="key-2", role=WorkerRole.EXPLORER
    )

    verdict = _admit(implementer, explorer, lease=lease)

    assert len(verdict.would_dispatch) == 2


def test_a_refused_request_does_not_consume_its_role_slot() -> None:
    # Folding a refusal forward would let a rejected worker occupy a
    # concurrency slot that nothing is using.
    lease = _lease()
    stale = _request(lease=lease, request_id="req-1", key="key-1", epoch=1)
    good = _request(lease=lease, request_id="req-2", key="key-2")

    verdict = _admit(stale, good, lease=lease)

    assert len(verdict.would_dispatch) == 1


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


def test_a_refusal_mints_a_rejected_receipt() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease, epoch=1), lease=lease)

    assert verdict.receipts[0].status is ReceiptStatus.REJECTED


def test_a_refusal_receipt_carries_a_deterministic_reason_code() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease, epoch=1), lease=lease)

    assert verdict.receipts[0].reason_code is RejectionReason.STALE_EPOCH


def test_a_refusal_receipt_names_no_served_model() -> None:
    # Nothing was served. Naming a plausible model here would be the exact
    # smuggling path the receipt's model-honesty validator exists to close.
    lease = _lease()

    verdict = _admit(_request(lease=lease, epoch=1), lease=lease)

    assert verdict.receipts[0].served_model is None


def test_an_admitted_shadow_dispatch_mints_no_receipt() -> None:
    # It did not run, so there is nothing to receipt. An ACCEPTED receipt would
    # require inventing a lineage and a served model for a worker that never
    # existed.
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease)

    assert verdict.receipts == ()


def test_the_worker_tree_marks_every_node_as_not_dispatched_by_default() -> None:
    """The broker admits; it does not run anything, so it cannot know.

    This was an unconditional invariant while nothing could dispatch. #11541
    armed the canary, and an invariant that has stopped being one is a
    falsehood — so the default stands and the caller holding the receipts says
    otherwise (see the test below).
    """
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease)

    assert verdict.worker_tree()[0]["dispatched"] is False


def test_a_dispatched_request_is_marked_dispatched_in_the_tree() -> None:
    # Without this the tree and the receipts contradict each other about one
    # request_id in the single record ADR-0137 B5's bar is read from.
    lease = _lease()
    request = _request(lease=lease)

    verdict = _admit(request, lease=lease)
    tree = verdict.worker_tree(frozenset({request.request_id}))

    assert tree[0]["dispatched"] is True


def test_only_the_named_requests_are_marked_dispatched() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease)

    assert (
        verdict.worker_tree(frozenset({"some-other-request"}))[0]["dispatched"] is False
    )


def test_the_worker_tree_carries_a_tier_never_a_concrete_model_id() -> None:
    lease = _lease()

    verdict = _admit(_request(lease=lease), lease=lease)

    assert verdict.worker_tree()[0]["model_requirement"] == (
        "literal_family:claude-sonnet"
    )


def test_a_yield_command_produces_no_dispatches_and_no_receipts() -> None:
    lease = _lease()

    verdict = ShadowDispatchBroker().admit(
        DirectorCommand(kind=DirectorCommandKind.YIELD, rationale="waiting on CI"),
        capsule=_capsule(lease),
        lease=lease,
        writer_lease=_writer_lease(lease),
        sandbox_verified=True,
        now=NOW,
        live_stage_label=READY_LABEL,
    )

    assert (verdict.would_dispatch, verdict.receipts) == ((), ())


# --------------------------------------------------------------------------
# What the director cannot have, enforced by the contract itself
# --------------------------------------------------------------------------


def test_a_director_cannot_name_a_concrete_model_id() -> None:
    lease = _lease()

    with pytest.raises(ValueError, match="concrete model"):
        WorkerDispatchRequest(
            request_id="req-1",
            driver_id=lease.driver_id,
            epoch=lease.epoch,
            phase_attempt=0,
            worker_role=WorkerRole.IMPLEMENTER,
            model_requirement=ModelRequirement(
                kind=ModelRequirementKind.CONCRETE_MODEL, value="glm-5.3"
            ),
            task_contract="do it",
            reason="because",
            expected_route_policy_revision=ROUTE_REVISION,
            idempotency_key="key-1",
        )


def test_a_director_cannot_invent_a_role_outside_the_catalog() -> None:
    lease = _lease()

    with pytest.raises(ValueError):
        _request(lease=lease, role="root_shell")  # type: ignore[arg-type]


def test_a_command_has_no_representation_for_a_label_or_merge_action() -> None:
    # The vocabulary is the enforcement: there is no command kind that could
    # move a label or merge a PR, so the director cannot ask for one.
    assert {kind.value for kind in DirectorCommandKind} == {
        "dispatch_workers",
        "yield",
        "finish",
    }


def test_a_capsule_refuses_an_unknown_field_such_as_a_credential() -> None:
    lease = _lease()

    with pytest.raises(ValueError):
        DirectorCapsule(
            lease=lease,
            issue_goal="goal",
            live_stage_label=READY_LABEL,
            route_policy_revision=ROUTE_REVISION,
            remaining_usd_budget=1.0,
            remaining_wall_clock_seconds=60,
            api_key="sk-real",  # type: ignore[call-arg]
        )

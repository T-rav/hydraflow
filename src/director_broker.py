"""The narrow deterministic broker between a director's request and reality (#11537).

A director may *ask*. This module decides, and in shadow mode that is the whole
of it: **there is no method here that dispatches anything.** That is deliberate
and is the strongest available form of "no production worker is dispatched by
Fable" — not a flag that could be flipped by accident, not a guard that could be
short-circuited, but the absence of the code that would do it.
``tests/architecture/test_director_no_authority.py`` pins that absence so a
later phase has to add the capability on purpose.

What the broker *does* have is the admission decision, and it delegates that
entirely to :func:`driver_contracts.admit_dispatch` — the pure, first-match-wins
rule table #11533 fixed. Reimplementing any part of it here would fork the rule
set that the canary's evidence bar counts against, so the broker's own job is
narrow: fold state forward correctly across a batch, and turn each verdict into
evidence.

**Evidence is minted honestly.** A refusal really happened, so it produces a
real :class:`driver_contracts.WorkerReceipt` with status ``REJECTED`` and a
deterministic reason code. An *admitted* request in shadow mode did **not** run,
so it produces no receipt at all — it produces a :class:`ShadowDispatch`, which
says "this is what would have been dispatched" and claims nothing else. Minting
an ``ACCEPTED`` receipt for a worker that never existed would require inventing
a lineage and a served model, and a contract whose whole purpose is to make
"a GLM model reported as Sonnet" a validation error must not be fed a fabricated
model id by the one component that is supposed to be observing.

What the director cannot obtain through this broker, by construction rather than
by check: a shell, an arbitrary model id, a credential, a label mutation, a merge,
or a process. The first is not in the vocabulary (``WorkerRole`` is a closed
set with no tool axis); the second is refused by ``WorkerDispatchRequest``'s own
validator; the third never enters the capsule (``extra="forbid"``, and no field
for it); the last three have no representation in ``DirectorCommandKind``, whose
three members are dispatch / yield / finish.

Decision path, no authority. It may not spawn a process, mutate a label or
write convergence state -- pinned by
``tests/architecture/test_director_no_authority.py``, which requires this
sentence and this module's ``DECISION_PATH_MODULES`` entry to travel together
in both directions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from driver_contracts import (
    WORKER_CATALOG,
    DirectorCommandKind,
    ReceiptStatus,
    RejectionReason,
    WorkerReceipt,
    WorkerTransport,
    WriteScope,
    admit_dispatch,
)

if TYPE_CHECKING:
    from datetime import datetime

    from driver_contracts import (
        DirectorCapsule,
        DirectorCommand,
        DriverLease,
        ModelRequirement,
        WorkerDispatchRequest,
        WorkerRole,
        WriterLease,
    )

logger = logging.getLogger("director_broker")


@dataclass(frozen=True)
class ShadowDispatch:
    """One child the director was allowed to run — whether or not it then ran.

    Carries the *requirement*, never a resolved model id: resolving a tier to a
    concrete model is the broker's job at dispatch time, and this record is
    made before it. In shadow mode there is no dispatch time at all and the
    requirement is the whole story; under #11541's armed canary the resolved id
    and the served model live on the :class:`driver_contracts.WorkerReceipt`,
    which is minted after the child has actually run. Recording a resolved id
    here would be a claim about a route that had not been taken *yet*, and on
    the shadow path one that never would be.
    """

    request_id: str
    idempotency_key: str
    role: WorkerRole
    write_scope: WriteScope
    model_requirement: ModelRequirement
    reason: str

    def as_tree_node(self, *, dispatched: bool = False) -> dict[str, object]:
        """The operator-status shape: what this child would have been.

        ``dispatched`` defaults to False because the broker cannot know: it
        admits, and something else runs the admitted request or does not. The
        caller that holds the receipts passes the answer.

        It used to be hardcoded False, which was an invariant while nothing
        could dispatch and became a **falsehood** the moment #11541 armed the
        canary — an armed observation carried ``dispatched: false`` in this
        tree beside an ``accepted`` receipt for the same ``request_id``, in the
        one operator-facing record ADR-0137 B5's bar is read from.
        """
        return {
            "request_id": self.request_id,
            "role": self.role.value,
            "write_scope": self.write_scope.value,
            "model_requirement": (
                f"{self.model_requirement.kind.value}:{self.model_requirement.value}"
            ),
            "reason": self.reason,
            "dispatched": dispatched,
        }


@dataclass(frozen=True)
class BrokerVerdict:
    """What the broker made of one director turn's command."""

    command_kind: DirectorCommandKind
    would_dispatch: tuple[ShadowDispatch, ...] = ()
    receipts: tuple[WorkerReceipt, ...] = ()

    @property
    def invalid_requests(self) -> int:
        """Requests the rule table refused. One of the canary's counters."""
        return len(self.receipts)

    @property
    def rejection_reasons(self) -> tuple[RejectionReason, ...]:
        return tuple(
            receipt.reason_code
            for receipt in self.receipts
            if receipt.reason_code is not None
        )

    @property
    def route_revisions(self) -> int:
        """Refusals caused specifically by a stale route-policy revision.

        Counted separately because #11537 names it separately: it measures the
        director working from a routing view that moved under it, which is a
        different failure from asking for something it may not have.
        """
        return sum(
            1
            for reason in self.rejection_reasons
            if reason is RejectionReason.ROUTE_POLICY_REVISION_STALE
        )

    def worker_tree(
        self, dispatched_ids: frozenset[str] = frozenset()
    ) -> list[dict[str, object]]:
        """The worker tree the operator status renders.

        Hypothetical in shadow mode, where *dispatched_ids* is empty and every
        node reads ``dispatched: false`` — which is then a fact rather than a
        default. Under the armed canary the caller passes the ids of the
        requests that produced a child that actually **ran** — every receipt
        carrying a lineage, whatever its status then says, so a reaped
        ``EXPIRED`` child and one ``REJECTED`` for its served model both count
        — so the tree and the receipts agree about the
        same ``request_id`` instead of contradicting each other.
        """
        return [
            dispatch.as_tree_node(dispatched=dispatch.request_id in dispatched_ids)
            for dispatch in self.would_dispatch
        ]


class ShadowDispatchBroker:
    """Admits or refuses each dispatch a director asks for. Runs nothing.

    Stateless across turns on purpose: every fence it applies is re-derived from
    the lease, the capsule and the live label handed to :meth:`admit`, so a
    replay of the same inputs yields the same verdict. Nothing about a previous
    turn is remembered here — the durable record of what happened lives in
    :mod:`director_shadow_log`, and the durable record of *convergence* stays
    where ADR-0137 requires it, on ``ConvergenceLedger``, which this module does
    not touch.
    """

    def admit(
        self,
        command: DirectorCommand,
        *,
        capsule: DirectorCapsule,
        lease: DriverLease,
        writer_lease: WriterLease,
        sandbox_verified: bool,
        now: datetime,
        live_stage_label: str,
        implementer_spawn_ids: frozenset[str] = frozenset(),
    ) -> BrokerVerdict:
        """Judge every dispatch in *command*, in order, and return the evidence.

        Batch state is folded forward exactly as ``admit_dispatch``'s contract
        requires: an admitted request's idempotency key and its role's in-flight
        count are visible to the requests that follow it. Folding a *refused*
        request forward would be wrong twice over — it would let a rejected
        worker consume a concurrency slot, and it would make a second request
        with the same key look like a duplicate of something that never
        happened.
        """
        if command.kind is not DirectorCommandKind.DISPATCH_WORKERS:
            return BrokerVerdict(command_kind=command.kind)

        seen_keys: set[str] = set()
        in_flight: dict[WorkerRole, int] = {}
        admitted: list[ShadowDispatch] = []
        receipts: list[WorkerReceipt] = []
        lease_state = writer_lease

        for request in command.dispatches:
            reason = admit_dispatch(
                request,
                lease=lease,
                now=now,
                live_stage_label=live_stage_label,
                route_policy_revision=capsule.route_policy_revision,
                writer_lease=lease_state,
                sandbox_verified=sandbox_verified,
                allowed_roles=capsule.allowed_roles,
                seen_idempotency_keys=frozenset(seen_keys),
                in_flight_for_role=in_flight.get(request.worker_role, 0),
                remaining_usd_budget=capsule.remaining_usd_budget,
                stop_requested=capsule.stop_requested,
                draining=capsule.draining,
                implementer_spawn_ids=implementer_spawn_ids,
            )
            if reason is not None:
                receipts.append(_refusal_receipt(request, reason, capsule=capsule))
                continue
            seen_keys.add(request.idempotency_key)
            in_flight[request.worker_role] = in_flight.get(request.worker_role, 0) + 1
            lease_state = _fold_writer_lease(lease_state, request)
            admitted.append(_shadow_dispatch(request))

        if receipts:
            logger.info(
                "director_broker: refused %d/%d shadow dispatches for #%d (%s)",
                len(receipts),
                len(command.dispatches),
                lease.issue_number,
                ", ".join(
                    sorted({r.reason_code.value for r in receipts if r.reason_code})
                ),
            )
        return BrokerVerdict(
            command_kind=command.kind,
            would_dispatch=tuple(admitted),
            receipts=tuple(receipts),
        )


def _fold_writer_lease(
    writer_lease: WriterLease, request: WorkerDispatchRequest
) -> WriterLease:
    """Mark the single-writer lease taken by an admitted write-capable request.

    Folded forward for the same reason the idempotency keys and the per-role
    counts are: ``admit_dispatch`` judges one request against a fixed snapshot
    and accumulates nothing itself. Without this, the second write-capable role
    in a batch sees an unheld lease and is admitted alongside the first, and
    the single-writer property — the one thing a lease exists for — would hold
    only across turns and not within one.

    Per-role ``max_concurrency`` already stops *two implementers*; this stops an
    implementer and a debugger, which are different roles sharing one worktree.
    """
    entry = WORKER_CATALOG[request.worker_role]
    if entry.write_scope is not WriteScope.ISSUE_WORKTREE:
        return writer_lease
    return writer_lease.model_copy(update={"holder_request_id": request.request_id})


def _shadow_dispatch(request: WorkerDispatchRequest) -> ShadowDispatch:
    entry = WORKER_CATALOG[request.worker_role]
    return ShadowDispatch(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        role=request.worker_role,
        write_scope=entry.write_scope,
        model_requirement=request.model_requirement,
        reason=request.reason,
    )


def _refusal_receipt(
    request: WorkerDispatchRequest,
    reason: RejectionReason,
    *,
    capsule: DirectorCapsule,
) -> WorkerReceipt:
    """A real receipt for a real refusal.

    ``served_model`` is left ``None`` because nothing was served — and the
    contract's model-honesty validator applies to *every* receipt naming a
    served model, so putting a plausible id here would be exactly the smuggling
    path that validator exists to close.
    """
    return WorkerReceipt(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        status=ReceiptStatus.REJECTED,
        reason_code=reason,
        worker_role=request.worker_role,
        transport=WorkerTransport.BROKERED,
        requested_model=request.model_requirement,
        route_policy_revision=capsule.route_policy_revision,
        output_contract_ok=False,
    )

"""``admit_dispatch``'s two ordered rule tables, swept row by row (#11723 F1).

``fencing`` and ``legality`` are first-match tables: the earliest true row is
the answer, so **order is the contract** and every row's reachability is part
of it. The test written to pin that pinned *one* adjacency — "the sharpest of
the ordered-table adjacencies" — and nine of the other ten adjacent swaps
survived the full suite. One of them was the harm the fix existed to prevent:
hoisting ``writer_conflict`` above ``writer_foreign`` reports a
held-foreign-lease theft event as ``writer_lease_held``, downgrading it out of
ADR-0137 B5's counter.

The subject here is the tuple, resolved from the live source, and the sweep is
over every row of it. Each row gets a witness that must be answered with
exactly that row's reason. No other row in either table carries the same
reason, so deleting a row makes its witness unanswerable — which is the
property ``docs/standards/parametrised_guards/README.md`` asks for: *deleting
any member of the subject sequence reddens something.*

The writer-lease witnesses trip more than one row on purpose, and the
``WriterLease`` in them **sets ``holder_request_id``**. The fixture this
replaces did not, so ``is_held`` was False and ``writer_conflict`` could never
be true — a docstring claiming "the ordinary theft shape trips BOTH
predicates" over a lease nobody held.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from driver_contracts import (
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
    WriterLease,
    admit_dispatch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The subject, resolved from the live source
# ---------------------------------------------------------------------------


def rule_table_reasons(table: str) -> tuple[str, ...]:
    """The ordered ``RejectionReason`` members of ``admit_dispatch``'s *table*.

    Read from the source rather than re-typed, so the witnesses below are
    pinned against the tuple that actually runs. A rename or a reshape that
    stops this finding rows returns ``()``, and the equality assertions — which
    compare against a non-empty witness tuple — fail closed rather than
    passing over nothing.
    """
    tree = ast.parse(
        (REPO_ROOT / "src" / "driver_contracts.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        target: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == table):
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        reasons: list[str] = []
        for row in node.value.elts:
            if not (isinstance(row, ast.Tuple) and len(row.elts) == 2):
                continue
            member = row.elts[1]
            if (
                isinstance(member, ast.Attribute)
                and isinstance(member.value, ast.Name)
                and member.value.id == "RejectionReason"
            ):
                reasons.append(RejectionReason[member.attr].value)
        return tuple(reasons)
    return ()


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _lease(**overrides: Any) -> DriverLease:
    base: dict[str, Any] = {
        "driver_id": "drv-1",
        "epoch": 3,
        "repo_slug": "T-rav/hydraflow",
        "issue_number": 11723,
        "phase": DriverPhase.PLAN,
        "expected_stage_label": "hydraflow-plan",
        "phase_attempt": 1,
        "expires_at": NOW + timedelta(minutes=30),
    }
    base.update(overrides)
    return DriverLease(**base)


def _request(**overrides: Any) -> WorkerDispatchRequest:
    base: dict[str, Any] = {
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
    return WorkerDispatchRequest(**base)


def _writer_lease(**overrides: Any) -> WriterLease:
    base: dict[str, Any] = {
        "driver_id": "drv-1",
        "epoch": 3,
        "worktree_base_digest": "base-abc",
        "worktree_head_digest": "head-def",
    }
    base.update(overrides)
    return WriterLease(**base)


def _review_scene(**overrides: Any) -> dict[str, Any]:
    """A REVIEW boundary with a fenced role — the lineage rows' only home."""
    scene: dict[str, Any] = {
        "request": _request(
            worker_role=WorkerRole.REVIEWER, requesting_spawn_id="spawn-fresh"
        ),
        "lease": _lease(
            phase=DriverPhase.REVIEW, expected_stage_label="hydraflow-review"
        ),
        "live_stage_label": "hydraflow-review",
    }
    scene.update(overrides)
    return scene


def _writer_scene(**overrides: Any) -> dict[str, Any]:
    """An IMPLEMENT boundary with a write-capable role.

    The writer-lease rows apply only to ``WriteScope.ISSUE_WORKTREE``, so a
    witness for any of them has to be an IMPLEMENTER at IMPLEMENT. Every one
    below hands over a lease that is actually HELD.
    """
    scene: dict[str, Any] = {
        "request": _request(worker_role=WorkerRole.IMPLEMENTER),
        "lease": _lease(
            phase=DriverPhase.IMPLEMENT, expected_stage_label="hydraflow-implement"
        ),
        "live_stage_label": "hydraflow-implement",
    }
    scene.update(overrides)
    return scene


def _admit(**overrides: Any) -> RejectionReason | None:
    kwargs: dict[str, Any] = {
        "lease": _lease(),
        "now": NOW,
        "live_stage_label": "hydraflow-plan",
        "route_policy_revision": "rev-7",
        "writer_lease": _writer_lease(),
        "remaining_usd_budget": 5.0,
        "sandbox_verified": True,
        "allowed_roles": frozenset(WorkerRole),
    }
    request = overrides.pop("request", None) or _request()
    kwargs.update(overrides)
    return admit_dispatch(request, **kwargs)


@dataclass(frozen=True)
class RowWitness:
    """One row of an ordered rule table, and an input that must reach it."""

    reason: RejectionReason
    scene: dict[str, Any] = field(default_factory=dict)
    also_trips: tuple[RejectionReason, ...] = ()
    """Rows BELOW this one that the same input also satisfies.

    This is where the ordering is pinned. A witness that trips only its own
    row proves reachability; one that trips its successors proves precedence,
    which is what an adjacent swap breaks.
    """


# ---------------------------------------------------------------------------
# The witnesses, in table order
# ---------------------------------------------------------------------------

FENCING_WITNESSES: tuple[RowWitness, ...] = (
    RowWitness(RejectionReason.STOP_FENCE, {"stop_requested": True, "draining": True}),
    RowWitness(RejectionReason.DRAINING, {"draining": True}),
    RowWitness(RejectionReason.SANDBOX_UNVERIFIED, {"sandbox_verified": False}),
    RowWitness(
        RejectionReason.DRIVER_IDENTITY_MISMATCH,
        {"request": _request(driver_id="drv-other")},
    ),
    RowWitness(RejectionReason.STALE_EPOCH, {"request": _request(epoch=4)}),
    RowWitness(
        RejectionReason.STALE_PHASE_ATTEMPT, {"request": _request(phase_attempt=2)}
    ),
    RowWitness(
        RejectionReason.LEASE_EXPIRED,
        {"lease": _lease(expires_at=NOW - timedelta(minutes=1))},
    ),
    RowWitness(
        RejectionReason.LIVE_LABEL_CHANGED, {"live_stage_label": "hydraflow-implement"}
    ),
    RowWitness(
        RejectionReason.ROLE_NOT_IN_CATALOG,
        # ``model_copy`` skips validation, which is the only way to hold a role
        # the catalog has never heard of — ``WORKER_CATALOG`` is total over
        # ``WorkerRole`` and a separate test keeps it that way.
        {"request": _request().model_copy(update={"worker_role": "ghost-role"})},
    ),
)

LEGALITY_WITNESSES: tuple[RowWitness, ...] = (
    RowWitness(
        RejectionReason.ROLE_PHASE_FORBIDDEN,
        {
            "lease": _lease(
                phase=DriverPhase.REVIEW, expected_stage_label="hydraflow-review"
            ),
            "live_stage_label": "hydraflow-review",
        },
    ),
    RowWitness(RejectionReason.ROLE_NOT_IN_CAPSULE, {"allowed_roles": frozenset()}),
    RowWitness(
        RejectionReason.LINEAGE_UNKNOWN,
        _review_scene(
            request=_request(
                worker_role=WorkerRole.REVIEWER, requesting_spawn_id="spawn-fresh"
            ).model_copy(update={"requesting_spawn_id": None})
        ),
    ),
    RowWitness(
        RejectionReason.SELF_REVIEW_FORBIDDEN,
        _review_scene(
            request=_request(
                worker_role=WorkerRole.REVIEWER, requesting_spawn_id="spawn-impl-1"
            ),
            implementer_spawn_ids=frozenset({"spawn-impl-1"}),
        ),
    ),
    RowWitness(
        RejectionReason.ROUTE_POLICY_REVISION_STALE,
        {"request": _request(expected_route_policy_revision="rev-6")},
    ),
    RowWitness(
        RejectionReason.DUPLICATE_IDEMPOTENCY_KEY,
        {"seen_idempotency_keys": frozenset({"idem-1"})},
    ),
    RowWitness(
        RejectionReason.DRIVER_IDENTITY_MISMATCH,
        _writer_scene(
            writer_lease=_writer_lease(
                driver_id="drv-other", epoch=99, holder_request_id="req-other"
            )
        ),
        also_trips=(RejectionReason.LEASE_EXPIRED, RejectionReason.WRITER_LEASE_HELD),
    ),
    RowWitness(
        RejectionReason.LEASE_EXPIRED,
        _writer_scene(
            writer_lease=_writer_lease(epoch=99, holder_request_id="req-other")
        ),
        also_trips=(RejectionReason.WRITER_LEASE_HELD,),
    ),
    RowWitness(
        RejectionReason.WRITER_LEASE_HELD,
        _writer_scene(writer_lease=_writer_lease(holder_request_id="req-other")),
    ),
    RowWitness(RejectionReason.FANOUT_OVERFLOW, {"in_flight_for_role": 1}),
    RowWitness(RejectionReason.BUDGET_EXHAUSTED, {"remaining_usd_budget": 0.0}),
)

_TABLES: dict[str, tuple[RowWitness, ...]] = {
    "fencing": FENCING_WITNESSES,
    "legality": LEGALITY_WITNESSES,
}


def _row_is_reachable(table: str, reason_value: str) -> bool:
    """Does the registered witness for *reason_value* still get that answer?

    The registry's ``detects_drop``. Deleting the row from the table makes the
    reason unreachable — no other row in the same table carries it — so this
    goes False, which is what "the drop reddens" means for an ordered table.
    """
    for witness in _TABLES[table]:
        if witness.reason.value == reason_value:
            return _admit(**witness.scene) is witness.reason
    return False


def fencing_row_is_reachable(reason_value: str) -> bool:
    return _row_is_reachable("fencing", reason_value)


def legality_row_is_reachable(reason_value: str) -> bool:
    return _row_is_reachable("legality", reason_value)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(_TABLES))
def test_the_witnesses_are_the_table_in_order(table: str) -> None:
    """The subject, by reference. Not a representative of it (#11723 F1).

    Equality including ORDER, because order is the contract of a first-match
    table: a row deleted, added, or moved reddens here before any behavioural
    assertion has to notice.
    """
    reasons = rule_table_reasons(table)

    assert reasons, (
        f"no rows extracted for `{table}` in src/driver_contracts.py — the "
        "subject could not be resolved. Fail closed: a sweep with no subject "
        "must not pass."
    )
    assert reasons == tuple(w.reason.value for w in _TABLES[table]), (
        f"`{table}` and its witnesses disagree. Every row of a first-match "
        "table needs an input that reaches it, or the row is unfalsifiable."
    )


@pytest.mark.parametrize(
    "witness", FENCING_WITNESSES, ids=[w.reason.value for w in FENCING_WITNESSES]
)
def test_every_fencing_row_is_the_answer_to_something(witness: RowWitness) -> None:
    assert _admit(**witness.scene) is witness.reason


@pytest.mark.parametrize(
    "witness", LEGALITY_WITNESSES, ids=[w.reason.value for w in LEGALITY_WITNESSES]
)
def test_every_legality_row_is_the_answer_to_something(witness: RowWitness) -> None:
    assert _admit(**witness.scene) is witness.reason


@pytest.mark.parametrize(
    "witness",
    [w for w in LEGALITY_WITNESSES if w.also_trips],
    ids=[w.reason.value for w in LEGALITY_WITNESSES if w.also_trips],
)
def test_a_witness_that_trips_later_rows_still_gets_the_earlier_answer(
    witness: RowWitness,
) -> None:
    """The precedence half, and the site F1 named.

    Each of these inputs satisfies its own row AND rows below it. If the table
    were reordered, the later row's reason would surface instead — which is
    exactly the theft-downgrade #11723 reproduced. Asserting the successors are
    genuinely satisfied is what stops this degenerating into the reachability
    test above.
    """
    reasons = rule_table_reasons("legality")
    order = {reason: index for index, reason in enumerate(reasons)}

    for later in witness.also_trips:
        assert order[later.value] > order[witness.reason.value], later
        # Remove the earlier rule's cause and the later one must surface,
        # which is the proof that the input really does satisfy both.
        assert _admit(**_without_earlier_cause(witness, later)) is later


def _without_earlier_cause(
    witness: RowWitness, later: RejectionReason
) -> dict[str, Any]:
    """The same scene with the earlier row's cause removed.

    The writer-lease trio share one operand, so "also trips" is demonstrated by
    healing the earlier clause rather than by re-deriving the predicate here —
    a re-derivation would be a second copy of the rule under test.
    """
    scene = dict(witness.scene)
    lease: WriterLease = scene["writer_lease"]
    if later is RejectionReason.LEASE_EXPIRED:
        scene["writer_lease"] = lease.model_copy(update={"driver_id": "drv-1"})
    elif later is RejectionReason.WRITER_LEASE_HELD:
        scene["writer_lease"] = lease.model_copy(
            update={"driver_id": "drv-1", "epoch": 3}
        )
    return scene


def test_the_writer_lease_witnesses_hold_a_lease_at_all() -> None:
    """The fixture defect underneath F1.

    ``WriterLease(...)`` without ``holder_request_id`` leaves ``is_held``
    False, so ``writer_conflict`` is unreachable and a docstring claiming "the
    ordinary theft shape trips BOTH predicates" describes a lease nobody
    holds. Asserted here rather than trusted, because that is the exact
    mistake this file replaces.
    """
    held = [
        witness
        for witness in LEGALITY_WITNESSES
        if witness.reason
        in {
            RejectionReason.DRIVER_IDENTITY_MISMATCH,
            RejectionReason.LEASE_EXPIRED,
            RejectionReason.WRITER_LEASE_HELD,
        }
    ]

    assert len(held) == 3
    for witness in held:
        assert witness.scene["writer_lease"].is_held is True, witness.reason


def test_the_base_scenario_admits() -> None:
    """Non-vacuity. Every assertion above expects a rejection; if the base
    scenario were itself inadmissible, each witness would be measuring the
    base's defect rather than its own row."""
    assert _admit() is None

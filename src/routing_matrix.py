"""The effective-route matrix and its before/after diff (ADR-0140).

An "effective route" is what the resolver *would* decide for one repository, one
worker role, one request face, and one model requirement — at one policy
revision. The matrix is that question asked for every combination at once, and
the whole point is the "at once": it is built with
:func:`hydraflow_gateway.routing_policy.explain_batch`, which resolves every
context against a **single** snapshot, because a matrix whose rows saw different
revisions is a race rather than a matrix (ADR-0139 D1).

Two things this module deliberately does not do:

* **It does not guess which model a role asks for.** The default requirement is
  the provider-neutral ``balanced`` capability — what ``route_shadow`` already
  records for a spawn that named no model. Compiling a role→model table out of
  the config's per-role dials would be the same maintained lie ADR-0139 refused
  when it declined to compile legacy dials into rung-9 policies. A caller that
  cares about a literal family passes it in.
* **It does not supply a legacy route.** A cell is a question about *policy*, and
  the legacy route is a per-spawn fact. So a cell no policy claims classifies as
  :attr:`CellState.UNMANAGED` — "legacy routing decides this one" — rather than
  borrowing a route from somewhere and calling it an effective one.

A bare ``provider_lock`` that leaves an Anthropic-lane requirement unmapped shows
up as :attr:`CellState.HELD`, and that is the matrix earning its keep: it is
exactly ADR-0139 D4's guard becoming visible *before* the policy is saved, rather
than as a surprise in the shadow log afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from driver_contracts import ModelRequirement, ModelRequirementKind, WorkerRole
from hydraflow_gateway.routing_policy import (
    DecisionOutcome,
    DecisionReason,
    PolicySource,
    RepoIdentity,
    RequestFace,
    RouteContext,
    SnapshotState,
    explain_batch,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from hydraflow_gateway.models import RepoClass
    from hydraflow_gateway.routing_policy import (
        AccountAvailability,
        PolicySnapshot,
        RouteDecision,
    )

DEFAULT_MATRIX_REQUIREMENT = ModelRequirement(
    kind=ModelRequirementKind.CAPABILITY, value="balanced"
)
"""What a spawn that named no model is recorded as asking for (``route_shadow``)."""

MATRIX_REQUEST_FACES: tuple[RequestFace, ...] = (
    RequestFace.AGENTIC,
    RequestFace.ONE_SHOT,
)
"""Both faces, because transport — and therefore governability — differs by face."""

MAX_MATRIX_REQUIREMENTS = 8
"""Bound on the caller-supplied dimension so a request cannot become a scan."""


class CellState(StrEnum):
    """What one cell of the matrix says about one route."""

    MANAGED = "managed"
    HELD = "held"
    REJECTED = "rejected"
    UNMANAGED = "unmanaged"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MatrixCell:
    """One resolved route, with the explanation that produced it attached."""

    role: WorkerRole
    request_face: RequestFace
    requirement: ModelRequirement
    decision: RouteDecision

    @property
    def key(self) -> str:
        """Stable identity for diffing and for a URL-addressable selection."""
        return (
            f"{self.role.value}|{self.request_face.value}|"
            f"{self.requirement.kind.value}:{self.requirement.value}"
        )

    @property
    def state(self) -> CellState:
        """Classify the decision into what an operator reads off the grid."""
        if self.decision.reason is DecisionReason.SNAPSHOT_UNAVAILABLE:
            return CellState.UNAVAILABLE
        if self.decision.policy_source is not PolicySource.MANAGED_POLICY:
            return CellState.UNMANAGED
        if self.decision.outcome is DecisionOutcome.SELECTED:
            return CellState.MANAGED
        if self.decision.outcome is DecisionOutcome.HELD:
            return CellState.HELD
        return CellState.REJECTED


@dataclass(frozen=True, slots=True)
class EffectiveMatrix:
    """Every cell for one repository, pinned to one policy revision."""

    repo: str
    policy_revision: int
    snapshot_hash: str
    snapshot_state: SnapshotState
    cells: tuple[MatrixCell, ...] = ()


@dataclass(frozen=True, slots=True)
class MatrixCellDiff:
    """One cell as it is now and as an edit would leave it."""

    key: str
    before: MatrixCell | None
    after: MatrixCell | None
    changed_fields: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether this route moves at all."""
        return bool(self.changed_fields)


def build_matrix_contexts(
    *,
    repo: str,
    repo_class: RepoClass,
    accounts: Sequence[AccountAvailability],
    requirements: Sequence[ModelRequirement] = (DEFAULT_MATRIX_REQUIREMENT,),
    faces: Sequence[RequestFace] = MATRIX_REQUEST_FACES,
) -> tuple[RouteContext, ...]:
    """Build one context per (role, face, requirement), in a deterministic order."""
    identity = RepoIdentity.from_canonical(repo)
    bounded = tuple(requirements)[:MAX_MATRIX_REQUIREMENTS] or (
        DEFAULT_MATRIX_REQUIREMENT,
    )
    return tuple(
        RouteContext(
            repo=identity,
            repo_class=repo_class,
            principal_id=role.value,
            worker_role=role,
            model_requirement=requirement,
            request_face=face,
            accounts=tuple(accounts),
            # No legacy route: a matrix cell asks what POLICY would do, and a
            # legacy route is a per-spawn fact this question does not have.
            legacy_route=None,
        )
        for role in WorkerRole
        for face in faces
        for requirement in bounded
    )


def build_effective_matrix(
    *,
    repo: str,
    repo_class: RepoClass,
    accounts: Sequence[AccountAvailability],
    snapshot: PolicySnapshot,
    snapshot_state: SnapshotState = SnapshotState.OK,
    requirements: Sequence[ModelRequirement] = (DEFAULT_MATRIX_REQUIREMENT,),
    faces: Sequence[RequestFace] = MATRIX_REQUEST_FACES,
) -> EffectiveMatrix:
    """Resolve every cell against ONE snapshot revision."""
    contexts = build_matrix_contexts(
        repo=repo,
        repo_class=repo_class,
        accounts=accounts,
        requirements=requirements,
        faces=faces,
    )
    decisions = explain_batch(contexts, snapshot, snapshot_state=snapshot_state)
    return EffectiveMatrix(
        repo=repo,
        policy_revision=snapshot.revision,
        snapshot_hash=snapshot.content_hash,
        snapshot_state=snapshot_state,
        cells=tuple(
            MatrixCell(
                # `worker_role` is populated for every context this module builds;
                # the fallback keeps the cell total rather than raising inside a
                # projection that a UI polls.
                role=context.worker_role or WorkerRole.IMPLEMENTER,
                request_face=context.request_face,
                requirement=context.model_requirement,
                decision=decision,
            )
            for context, decision in zip(contexts, decisions, strict=True)
        ),
    )


_DIFFED_FIELDS = ("state", "account_id", "provider_binding", "effective_model")


def diff_matrices(
    before: EffectiveMatrix, after: EffectiveMatrix
) -> tuple[MatrixCellDiff, ...]:
    """Pair the two matrices by cell key and name what each edit moves.

    ``policy_id`` is deliberately *not* a diffed field on its own: an operator
    renaming a rule that resolves identically has not changed a route, and a
    before/after view that shouted about it would train them to ignore it.
    """
    prior = {cell.key: cell for cell in before.cells}
    following = {cell.key: cell for cell in after.cells}
    return tuple(
        MatrixCellDiff(
            key=key,
            before=prior.get(key),
            after=following.get(key),
            changed_fields=_changed_fields(prior.get(key), following.get(key)),
        )
        for key in sorted(set(prior) | set(following))
    )


def _changed_fields(
    before: MatrixCell | None, after: MatrixCell | None
) -> tuple[str, ...]:
    if before is None or after is None:
        return ("presence",)
    return tuple(
        field for field in _DIFFED_FIELDS if _read(before, field) != _read(after, field)
    )


def _read(cell: MatrixCell, field: str) -> object:
    if field == "state":
        return cell.state
    return getattr(cell.decision, field)

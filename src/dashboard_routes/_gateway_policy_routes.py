"""Operator routing-policy workspace routes (ADR-0140, issue #11538).

Five endpoints under ``/api/gateway/policies``. Four are reads; exactly one
writes, and it is the first write route on this dashboard's routing surface —
so it is the one that spends the precondition ADR-0138 §D5 recorded:

* it refuses unless the dashboard is bound to loopback, **whatever credential is
  presented**, and
* it refuses unless an authenticated operator identity is presented, which
  supplies the ``actor`` on the audit record. The mutation body cannot claim one:
  :class:`~hydraflow_gateway.routing_workspace.PolicyMutation` forbids extra
  fields and declares no actor.

**These routes are not a gateway proxy.** ADR-0139 put the policy snapshot on the
HydraFlow side, under the repository's own data root, because that is where the
shadow resolver reads it at spawn time and because the gateway container and the
factory host share no filesystem. The write plane therefore lands where the read
plane already is: one authority, no round trip, and no second copy of a
revision counter to keep in step. The issue's prose anticipated a gateway
mutation endpoint proxied from here; the code after #11639 says otherwise, and
this follows the code.

Aggregate (``repo=__all__``) is read-only by construction: it serves a per-repo
summary and every other policy route refuses it, so an aggregate write cannot be
mistaken for a host-admin one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from dashboard_routes._common import REPO_ALL
from driver_contracts import ModelRequirement, ModelRequirementKind
from hydraflow_gateway.routing_policy import canonicalize_repo
from hydraflow_gateway.routing_workspace import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    MutationRejection,
    PolicyMutation,
    PolicyMutationRejected,
    PolicyWorkspace,
)
from operator_identity import WriteGate, authenticate_operator, write_gate
from route_shadow import local_account_availability, repo_class_for, routing_dir
from route_types import RepoSlugParam
from routing_matrix import (
    DEFAULT_MATRIX_REQUIREMENT,
    MAX_MATRIX_REQUIREMENTS,
    build_effective_matrix,
    diff_matrices,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from config import HydraFlowConfig
    from hydraflow_gateway.routing_audit import AuditRecord
    from hydraflow_gateway.routing_policy import (
        PolicyValidationIssue,
        RoutingPolicy,
    )
    from hydraflow_gateway.routing_workspace import (
        PolicyPreview,
        WorkspaceView,
    )
    from routing_matrix import EffectiveMatrix, MatrixCell, MatrixCellDiff

#: A refused mutation maps to the status an operator's client should act on.
#: 409 means "reload and try again"; 422 means "this edit is wrong"; 404 means
#: "that policy is not here".
_REJECTION_STATUS: dict[MutationRejection, int] = {
    MutationRejection.STALE_REVISION: 409,
    MutationRejection.SNAPSHOT_CORRUPT: 409,
    MutationRejection.AUDIT_CHAIN_BROKEN: 409,
    MutationRejection.JOURNAL_UNREADABLE: 409,
    MutationRejection.POLICY_ALREADY_EXISTS: 409,
    MutationRejection.POLICY_NOT_FOUND: 404,
    MutationRejection.OUT_OF_SCOPE: 422,
    MutationRejection.UNKNOWN_REVISION: 422,
    MutationRejection.MALFORMED_MUTATION: 422,
    MutationRejection.CREDENTIAL_SHAPED_VALUE: 422,
    MutationRejection.VALIDATION_FAILED: 422,
}

_GATE_DETAIL: dict[WriteGate, str] = {
    WriteGate.WORKSPACE_DISABLED: (
        "the routing policy workspace is switched off "
        "(gateway_policy_workspace_enabled)"
    ),
    WriteGate.DASHBOARD_NOT_LOOPBACK: (
        "policy writes are disabled while the dashboard is bound beyond "
        "loopback; there is no operator authorization boundary on a shared "
        "socket (ADR-0138 D5)"
    ),
    WriteGate.NO_OPERATOR_IDENTITY: (
        "policy writes need an authenticated operator identity; set "
        "HYDRAFLOW_OPERATOR_TOKEN on the dashboard host"
    ),
}


def build_gateway_policy_router(
    config: HydraFlowConfig,
    ctx: Any = None,
    *,
    env: dict[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the ``/api/gateway/policies`` router.

    *env* and *clock* are the injectable boundaries: production reads the real
    environment and wall clock, tests supply their own so the operator
    credential and the audit timestamps are deterministic.
    """
    router = APIRouter(prefix="/api/gateway/policies", tags=["gateway"])
    now = clock or (lambda: datetime.now(UTC))

    def _config_for(repo: str | None) -> HydraFlowConfig:
        if ctx is None:
            return config
        resolved, _state, _bus, _orch = ctx.resolve_runtime(repo)
        return resolved

    def _workspace(repo: str | None) -> PolicyWorkspace:
        """Resolve the one repository this request edits, or refuse the scope."""
        if repo is not None and repo.strip().lower() == REPO_ALL:
            raise HTTPException(
                status_code=400,
                detail=(
                    "repo=__all__ is read-only for policy; pass one owner/repo. "
                    "Class and global rules belong to a host-admin scope this "
                    "phase does not build."
                ),
            )
        resolved = _config_for(repo)
        canonical = canonicalize_repo(str(getattr(resolved, "repo", "") or ""))
        if canonical is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "this repository has no canonical owner/repo identity, so no "
                    "policy can name it (ADR-0139 D2)"
                ),
            )
        return PolicyWorkspace(routing_dir(resolved), repo=canonical)

    def _gate() -> WriteGate:
        # The HOST config, deliberately: the bind is one socket for the whole
        # dashboard, so a per-repo runtime's copy of it would be a second answer
        # to a question the operating system already answered once.
        return write_gate(config, env=env)

    @router.get("")
    async def read_policies(repo: RepoSlugParam = None) -> dict[str, Any]:
        """The current snapshot, which policies are editable, and the write gate."""
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return _aggregate_summary(config, ctx, gate=_gate())
        workspace = _workspace(repo)
        return _view_json(workspace.read(), gate=_gate())

    @router.get("/effective")
    async def read_effective_routes(
        repo: RepoSlugParam = None,
        requirement: list[str] = Query(default=[]),  # noqa: B008
    ) -> dict[str, Any]:
        """The repository × role × face matrix, pinned to one policy revision."""
        workspace = _workspace(repo)
        view = workspace.read()
        matrix = build_effective_matrix(
            repo=workspace.repo,
            repo_class=repo_class_for(_config_for(repo)),
            accounts=local_account_availability(),
            snapshot=view.snapshot,
            snapshot_state=view.state,
            requirements=_requirements(requirement),
        )
        return _matrix_json(matrix)

    @router.post("/preview")
    async def preview_mutation(
        body: PolicyMutation, repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        """Resolve a candidate edit and its before/after matrix, writing nothing.

        Deliberately not behind the write gate: it has no side effect, returns no
        credential, and a builder that could not validate until it was authorized
        would push operators to save first and look afterwards.
        """
        workspace = _workspace(repo)
        preview = workspace.preview(body)
        repo_class = repo_class_for(_config_for(repo))
        accounts = local_account_availability()
        before = build_effective_matrix(
            repo=workspace.repo,
            repo_class=repo_class,
            accounts=accounts,
            snapshot=preview.before,
            snapshot_state=preview.snapshot_state,
        )
        after = build_effective_matrix(
            repo=workspace.repo,
            repo_class=repo_class,
            accounts=accounts,
            snapshot=preview.after,
            snapshot_state=preview.snapshot_state,
        )
        return _preview_json(preview, before=before, after=after)

    @router.post("/mutations")
    async def apply_mutation(
        body: PolicyMutation, request: Request, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Commit one revision-safe edit. The only write route in this module."""
        gate = _gate()
        if gate is not WriteGate.ENABLED:
            # Before authentication on purpose: a credential cannot make a
            # non-loopback bind safe, and saying so is the actionable answer.
            return _error(403, gate.value, _GATE_DETAIL[gate])
        identity = authenticate_operator(request.headers.get("authorization"), env=env)
        if identity is None:
            return JSONResponse(
                {
                    "code": "unauthenticated-operator",
                    "detail": "present the operator bearer token to write policy",
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        workspace = _workspace(repo)
        try:
            # Blocking: an advisory file lock plus two fsync'd writes. Handing it
            # to a thread keeps one operator's save off the event loop every
            # other dashboard poll shares.
            result = await asyncio.to_thread(
                workspace.apply, body, actor=identity.actor, now=now()
            )
        except PolicyMutationRejected as rejected:
            return _rejection(rejected)
        except OSError as exc:
            return _error(
                503,
                "storage-unavailable",
                f"the policy store could not be written: {exc}",
            )
        return JSONResponse(
            {
                "revision": result.revision,
                "prior_revision": result.prior_revision,
                "content_hash": result.content_hash,
                "audit_seq": result.audit_seq,
                "actor": identity.actor,
                "diff": result.diff.to_json_dict(),
                "policies": [_policy_json(p) for p in result.policies],
            }
        )

    @router.get("/audit")
    async def read_audit(
        repo: RepoSlugParam = None,
        limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    ) -> dict[str, Any]:
        """The append-only mutation history and whether the chain still verifies."""
        history = _workspace(repo).history(limit=limit)
        return {
            "records": [_record_json(record) for record in history.records],
            "truncated": history.truncated,
            "verified": history.verification.ok,
            "record_count": history.verification.records,
            "broken_at_seq": history.verification.broken_at_seq,
        }

    return router


def _requirements(raw: Sequence[str]) -> tuple[ModelRequirement, ...]:
    """Parse ``kind:value`` requirement selectors, or refuse the request.

    Refusing beats silently dropping one: a matrix that quietly skipped the row
    an operator asked about would be read as "that route is unaffected".
    """
    if not raw:
        return (DEFAULT_MATRIX_REQUIREMENT,)
    if len(raw) > MAX_MATRIX_REQUIREMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"at most {MAX_MATRIX_REQUIREMENTS} requirement rows per matrix",
        )
    parsed: list[ModelRequirement] = []
    for entry in raw:
        kind, separator, value = entry.partition(":")
        try:
            if not separator:
                raise ValueError(entry)
            parsed.append(
                ModelRequirement(
                    kind=ModelRequirementKind(kind.strip()), value=value.strip()
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"unrecognised model requirement {entry!r}",
            ) from exc
    return tuple(parsed)


def _aggregate_summary(
    config: HydraFlowConfig, ctx: Any, *, gate: WriteGate
) -> dict[str, Any]:
    """One row per registered repository. Read-only, and it says so."""
    runtimes = (
        [(config, "")]
        if ctx is None
        else [(cfg, slug) for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(REPO_ALL)]
    )
    repos: list[dict[str, Any]] = []
    for cfg, slug in runtimes:
        canonical = canonicalize_repo(str(getattr(cfg, "repo", "") or ""))
        if canonical is None:
            continue
        view = PolicyWorkspace(routing_dir(cfg), repo=canonical).read()
        repos.append(
            {
                "repo": canonical,
                "slug": slug or canonical.replace("/", "-"),
                "state": view.state.value,
                "revision": view.revision,
                "policy_count": len(view.policies),
                "editable_count": len(view.editable_policy_ids),
                "issue_count": len(view.issues),
            }
        )
    return {
        "scope": "aggregate",
        "editable": False,
        "write_gate": gate.value,
        "repos": repos,
    }


def _view_json(view: WorkspaceView, *, gate: WriteGate) -> dict[str, Any]:
    return {
        "scope": "repo",
        "repo": view.repo,
        "state": view.state.value,
        "revision": view.revision,
        "content_hash": view.content_hash,
        "policies": [_policy_json(policy) for policy in view.policies],
        "editable_policy_ids": list(view.editable_policy_ids),
        "issues": [_issue_json(issue) for issue in view.issues],
        "write_gate": gate.value,
        "editable": gate is WriteGate.ENABLED,
    }


def _preview_json(
    preview: PolicyPreview, *, before: EffectiveMatrix, after: EffectiveMatrix
) -> dict[str, Any]:
    return {
        "writable": preview.writable,
        "stale": preview.stale,
        "rejection": None if preview.rejection is None else preview.rejection.value,
        "expected_revision": preview.before.revision,
        "next_revision": preview.after.revision,
        "issues": [_issue_json(issue) for issue in preview.issues],
        "diff": preview.diff.to_json_dict(),
        "before": _matrix_json(before),
        "after": _matrix_json(after),
        "cells": [_cell_diff_json(entry) for entry in diff_matrices(before, after)],
    }


def _matrix_json(matrix: EffectiveMatrix) -> dict[str, Any]:
    return {
        "repo": matrix.repo,
        "policy_revision": matrix.policy_revision,
        "snapshot_hash": matrix.snapshot_hash,
        "snapshot_state": matrix.snapshot_state.value,
        "cells": [_cell_json(cell) for cell in matrix.cells],
    }


def _cell_json(cell: MatrixCell) -> dict[str, Any]:
    decision = cell.decision
    return {
        "key": cell.key,
        "role": cell.role.value,
        "request_face": cell.request_face.value,
        "requirement": cell.requirement.model_dump(mode="json"),
        "state": cell.state.value,
        "outcome": decision.outcome.value,
        "reason": decision.reason.value,
        "policy_source": decision.policy_source.value,
        "policy_id": decision.policy_id,
        "policy_revision": decision.policy_revision,
        "account_id": decision.account_id,
        "provider_binding": (
            None
            if decision.provider_binding is None
            else decision.provider_binding.value
        ),
        "effective_model": decision.effective_model,
        # The pinned trace, returned WITH the matrix: selecting a cell must never
        # re-resolve against a newer revision than the grid was drawn from.
        "explanation": decision.explanation.model_dump(mode="json"),
    }


def _cell_diff_json(entry: MatrixCellDiff) -> dict[str, Any]:
    return {
        "key": entry.key,
        "changed": entry.changed,
        "changed_fields": list(entry.changed_fields),
        "before": None if entry.before is None else _cell_json(entry.before),
        "after": None if entry.after is None else _cell_json(entry.after),
    }


def _record_json(record: AuditRecord) -> dict[str, Any]:
    return {
        "seq": record.seq,
        "recorded_at": record.recorded_at,
        "record_hash": record.record_hash,
        "prev_hash": record.prev_hash,
        "payload": record.payload,
    }


def _policy_json(policy: RoutingPolicy) -> dict[str, Any]:
    return policy.model_dump(mode="json")


def _issue_json(issue: PolicyValidationIssue) -> dict[str, Any]:
    return issue.model_dump(mode="json")


def _rejection(rejected: PolicyMutationRejected) -> JSONResponse:
    return JSONResponse(
        {
            "code": rejected.code.value,
            "detail": rejected.detail,
            "actual_revision": rejected.actual_revision,
            "issues": [_issue_json(issue) for issue in rejected.issues],
        },
        status_code=_REJECTION_STATUS[rejected.code],
    )


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status_code)

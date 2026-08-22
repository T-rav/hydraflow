"""The enforcement canary: one repository, one transport, one off-switch (ADR-0141).

ADR-0139 built a resolver whose answer every spawn seam discarded. This module is
where that discard is removed — for a deliberately narrow slice, and for nothing
else. A spawn is *inside the canary* only when all of the following hold:

1. ``config.gateway_enforcement_canary_repo`` names one canonical ``owner/repo``
   and this repository is exactly it;
2. the route legacy routing already chose transits the **gateway** — policy binds
   what reaches the tap, and the canary never promotes traffic onto it;
3. the repository's identity is canonical, not the lossy runtime slug (ADR-0139
   §D2 refuses that join in both directions).

Everything else — every other repository, every direct-Anthropic or direct-z.ai
spawn, every one-shot HTTP backend — returns ``None`` from the first predicate
and runs byte-identical code to the phase before this one.

Inside the slice exactly one thing changes on this side of the boundary: the
``--model`` the child is spawned with. The *account* is not chosen here; the
gateway derives it from that model at mint time, so a policy edit cannot make
HydraFlow reach for a credential the gateway did not authorise. A held or
rejected decision raises :class:`EnforcementRefused` before any credential is
minted, which is the whole of "cannot fall through to ambient credentials".

**The off-switch is one field.** Clearing ``gateway_enforcement_canary_repo``
disarms every clause above on the next spawn, with no restart, no policy edit,
and no gateway change. It is empty by default, so an untouched deployment has
never been enforced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from driver_contracts import ModelRequirement, WorkerRole
from hydraflow_gateway.routing_policy import (
    DecisionOutcome,
    PolicySnapshot,
    RepoIdentityVersion,
    RequestFace,
    RouteContext,
    RouteDecision,
    SnapshotState,
    canonicalize_repo,
    explain,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore
from prompt_telemetry import rewrite_command_model
from route_shadow import (
    build_route_context,
    local_account_availability,
    policy_snapshot_path,
    repo_class_for,
)
from routing_matrix import build_effective_matrix, diff_matrices

if TYPE_CHECKING:
    from collections.abc import Sequence

    from config import HydraFlowConfig
    from hydraflow_gateway.routing_policy import AccountAvailability
    from route_shadow import RouteStage
    from routing_matrix import MatrixCellDiff


class EnforcementRefused(RuntimeError):
    """A governed spawn was held or rejected; it must not run at all.

    Raised *before* a gateway credential is minted, so a refused route has no
    path to an ambient or direct provider key — the failure is a pre-spawn crash
    at every seam, exactly like a failed mint already is.
    """

    def __init__(self, decision: RouteDecision) -> None:
        super().__init__(
            f"routing policy {decision.outcome.value} this spawn: "
            f"{decision.reason.value} (policy={decision.policy_id}, "
            f"revision={decision.policy_revision})"
        )
        self.decision = decision


@dataclass(frozen=True, slots=True)
class EnforcedRoute:
    """One governed spawn's binding: what to run, and what authorised it."""

    decision: RouteDecision
    context: RouteContext
    effective_model: str
    dispatch_id: str
    mint_attempt_id: str

    @property
    def requirement(self) -> ModelRequirement:
        """What the spawn asked for, in ADR-0137's shared contract."""
        return self.context.model_requirement

    @property
    def worker_role(self) -> WorkerRole | None:
        """The canonical role this principal names, or ``None`` (ADR-0138 §D6)."""
        return self.context.worker_role

    @property
    def requested_model(self) -> str:
        """The model legacy routing had chosen before the policy answered."""
        legacy = self.context.legacy_route
        return "" if legacy is None else legacy.model

    def apply_to_command(self, cmd: list[str]) -> list[str]:
        """Return *cmd* spawning on the effective model. Never mutates the input.

        A route the policy did not move returns the identical list, so an
        unmanaged spawn inside the canary repository is byte-identical to the
        one it would have been.
        """
        if self.effective_model == self.requested_model:
            return cmd
        return rewrite_command_model(cmd, self.effective_model)


def canary_repo(config: HydraFlowConfig) -> str | None:
    """The one canonical repository the canary is armed for, or ``None``."""
    raw = str(getattr(config, "gateway_enforcement_canary_repo", "") or "")
    return canonicalize_repo(raw)


def canary_armed(config: HydraFlowConfig) -> bool:
    """Whether enforcement is armed at all on this host. The one-action switch."""
    return canary_repo(config) is not None


def canary_covers(config: HydraFlowConfig, context: RouteContext) -> bool:
    """Whether this exact spawn is inside the canary's bound."""
    armed = canary_repo(config)
    if armed is None:
        return False
    if context.repo.version is not RepoIdentityVersion.CANONICAL:
        return False
    if context.repo.canonical != armed:
        return False
    legacy = context.legacy_route
    # ``governed`` is transport == gateway. A spawn legacy routing sent direct is
    # not traffic a gateway policy can bind, and pulling it onto the tap would be
    # a far larger change than a canary is allowed to make.
    return legacy is not None and legacy.governed


def enforce_canary_route(
    *,
    config: HydraFlowConfig,
    principal_id: str,
    stages: Sequence[RouteStage],
    final_provider: str,
    final_model: str,
    request_face: RequestFace,
) -> EnforcedRoute | None:
    """Return the route policy binds this spawn to, or ``None`` when outside.

    Raises :class:`EnforcementRefused` when the spawn *is* inside the canary and
    the resolver held or rejected it — including on a corrupt snapshot, because
    missing policy evidence must never present as a coherent "no policy" state.
    """
    if not canary_armed(config):
        return None
    context = build_route_context(
        config=config,
        principal_id=principal_id,
        final_provider=final_provider,
        final_model=final_model,
        request_face=request_face,
        stages=stages,
    )
    if not canary_covers(config, context):
        return None
    loaded = RoutingPolicyStore(policy_snapshot_path(config)).load()
    decision = explain(context, loaded.snapshot, snapshot_state=loaded.state)
    if decision.outcome is not DecisionOutcome.SELECTED:
        raise EnforcementRefused(decision)
    legacy = context.legacy_route
    # A ``legacy-compatibility`` decision reports the route that was already
    # chosen, so ``effective_model`` is the model the spawn already had and
    # ``apply_to_command`` is a no-op.
    effective = decision.effective_model or (legacy.model if legacy else "")
    if not effective:
        raise EnforcementRefused(decision)
    return EnforcedRoute(
        decision=decision,
        context=context,
        effective_model=effective,
        dispatch_id=uuid.uuid4().hex,
        mint_attempt_id=uuid.uuid4().hex,
    )


def canary_blast_radius(
    *,
    config: HydraFlowConfig,
    snapshot: PolicySnapshot,
    snapshot_state: SnapshotState = SnapshotState.OK,
    accounts: Sequence[AccountAvailability] | None = None,
) -> tuple[MatrixCellDiff, ...]:
    """Every effective route this snapshot moves for the armed canary repository.

    The operator-facing statement of the bound, computed from ADR-0140's
    before/after matrix rather than claimed in prose: the "before" side is the
    empty policy set — what the repository routes to with the canary disarmed —
    and the "after" side is the snapshot as written. A disarmed canary moves
    nothing and returns an empty tuple, which is the same answer by a shorter
    route.
    """
    armed = canary_repo(config)
    if armed is None:
        return ()
    available = (
        tuple(accounts) if accounts is not None else local_account_availability()
    )
    repo_class = repo_class_for(config)
    before = build_effective_matrix(
        repo=armed,
        repo_class=repo_class,
        accounts=available,
        snapshot=PolicySnapshot.empty(),
    )
    after = build_effective_matrix(
        repo=armed,
        repo_class=repo_class,
        accounts=available,
        snapshot=snapshot,
        snapshot_state=snapshot_state,
    )
    return tuple(diff for diff in diff_matrices(before, after) if diff.changed)

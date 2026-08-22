"""Shadow routing: record what policy *would* choose, beside what legacy did (ADR-0139).

Legacy routing stays authoritative. This module observes it. At each spawn seam
it compiles the route the legacy dials actually produced into a
:class:`~hydraflow_gateway.routing_policy.LegacyRoute`, asks the pure resolver
what it would have chosen from the current policy snapshot, and appends both to
a hash-linked audit chain. Nothing here returns a route to the caller, and
nothing here can change one — :func:`record_route_shadow` returns ``None`` or a
record, never a provider or a command.

Three properties are deliberate:

* **Off unless a real config says otherwise.** The kill switch is checked with
  ``is not True``, so a ``MagicMock`` config in an unrelated test cannot turn
  shadow recording on by being truthy — the footgun that this repo's
  ``gateway_fleet_ratchet_enabled`` check already guards against.
* **A dead sink is not a routing event.** Every failure the sink can plausibly
  raise (unwritable data root, full disk) is swallowed after
  ``reraise_on_credit_or_bug``, so the spawn proceeds exactly as it would have.
  Genuine bugs still propagate, by the same house rule: a silently wrong shadow
  is worse than a loud one, and ``tests/regressions/
  test_issue_11536_shadow_route_is_inert.py`` pins the routing bytes either way.
* **The legacy mechanism is named, not laundered.** HydraFlow pins several
  loops to z.ai through per-role ``*_provider`` dials. Those spawns do not go
  through policy, and the record says so: ``mechanism=role-dial`` with the dial
  that decided it, and ``policy_source=legacy-compatibility`` on the decision.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from credit_failover import zai_key_present
from driver_contracts import ModelRequirement, ModelRequirementKind
from exception_classify import exc_detail, reraise_on_credit_or_bug
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, RepoClass, legacy_account_id
from hydraflow_gateway.routing_audit import RoutingAuditLog
from hydraflow_gateway.routing_policy import (
    ROUTING_DECISION_SCHEMA_VERSION,
    AccountAvailability,
    DecisionOutcome,
    LegacyRoute,
    LegacyRouteMechanism,
    RepoIdentity,
    RequestFace,
    RouteContext,
    RouteDecision,
    RouteTransport,
    canonical_worker_role,
    explain,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("route_shadow")

ROUTING_DIR_NAME = "routing"
SHADOW_DECISION_FILENAME = "shadow-decisions.jsonl"

_GATEWAY = "gateway"
_ONE_SHOT_HTTP_PROVIDERS = frozenset({"openrouter", "zai", "kimi"})
"""Providers that mean an OpenAI-compatible HTTP call at the one-shot seam.

``zai`` is in both worlds and that is exactly why transport is derived from the
request face rather than the provider name: at the agentic seam ``zai`` is the
Claude CLI pointed at GLM's Anthropic-shaped endpoint (a harness), while at the
one-shot seam it is a direct HTTP backend the gateway never sees.
"""

_FAMILY_ALIASES = {"opus": "claude-opus", "sonnet": "claude-sonnet"}


class ShadowDivergence(StrEnum):
    """How a proposed route differs from the route that actually ran."""

    NONE = "none"
    PROVIDER = "provider"
    MODEL = "model"
    PROVIDER_AND_MODEL = "provider-and-model"
    NOT_SELECTED = "not-selected"


class RouteStage(BaseModel):
    """One legacy routing stage and the provider it left the spawn on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism: LegacyRouteMechanism
    provider: str = Field(min_length=1, max_length=64)
    detail: str = Field(default="", max_length=200)


class ShadowDecision(BaseModel):
    """One governed spawn's proposed route recorded beside its actual route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTING_DECISION_SCHEMA_VERSION
    recorded_at: datetime
    principal_id: str = Field(min_length=1, max_length=256)
    issue_number: int | None = None
    pr_number: int | None = None
    actual: LegacyRoute
    proposed: RouteDecision
    agreed: bool
    divergence: ShadowDivergence


def routing_dir(config: HydraFlowConfig) -> Path:
    """The per-repo directory holding this repo's policy snapshot and audit chain."""
    return config.repo_data_root / ROUTING_DIR_NAME


def policy_snapshot_path(config: HydraFlowConfig) -> Path:
    """Where this repo's durable policy snapshot lives."""
    from hydraflow_gateway.routing_store import (  # noqa: PLC0415
        POLICY_SNAPSHOT_FILENAME,
    )

    return routing_dir(config) / POLICY_SNAPSHOT_FILENAME


def shadow_decision_log_path(config: HydraFlowConfig) -> Path:
    """Where this repo's append-only shadow decision chain lives."""
    return routing_dir(config) / SHADOW_DECISION_FILENAME


def classify_legacy_mechanism(stages: Sequence[RouteStage]) -> RouteStage:
    """Return the stage that actually decided the route.

    The last stage that *changed* the provider is the one an operator means when
    they ask "why did this spawn go to GLM?". When nothing moved it, the answer
    is the first stage — the dial the spawn started on.
    """
    if not stages:
        raise ValueError("a legacy route must name at least one stage")
    for index in range(len(stages) - 1, 0, -1):
        if stages[index].provider != stages[index - 1].provider:
            return stages[index]
    return stages[0]


def provider_binding_for(provider: str, model: str) -> ProviderBinding:
    """Map a resolved harness provider + model onto its upstream account binding.

    Mirrors ``runner_utils.harness_billing_provider``: the gateway's own binding
    is decided by the model (GLM ids bind to z.ai), while a direct lane binds to
    whatever it is.
    """
    lane = provider.strip().lower()
    if lane == _GATEWAY:
        lane = "zai" if model.strip().lower().startswith("glm") else "claude"
    if lane in {"zai", "kimi", "openrouter"}:
        return ProviderBinding.ZAI_HARNESS
    return ProviderBinding.ANTHROPIC


def transport_for(provider: str, face: RequestFace) -> RouteTransport:
    """Classify how a spawn reaches its upstream, and so whether policy governs it."""
    lane = provider.strip().lower()
    if lane == _GATEWAY:
        return RouteTransport.GATEWAY
    if face is RequestFace.ONE_SHOT and lane in _ONE_SHOT_HTTP_PROVIDERS:
        return RouteTransport.DIRECT_HTTP
    return RouteTransport.HARNESS_DIRECT


def requirement_for_model(model: str) -> ModelRequirement:
    """Classify what a legacy spawn actually asked for, in the shared contract.

    A bare CLI alias (``opus`` / ``sonnet``) *is* a literal-family request — that
    is what the alias means. A fully qualified id (``claude-opus-4-8``,
    ``glm-5.2``) is a concrete-model request. An empty model means the spawn
    named none and inherits the harness default, which is the one genuinely
    provider-neutral case, so it is recorded as a ``balanced`` capability.
    """
    candidate = model.strip().lower()
    if not candidate:
        return ModelRequirement(kind=ModelRequirementKind.CAPABILITY, value="balanced")
    family = _FAMILY_ALIASES.get(candidate)
    if family is not None:
        return ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value=family)
    return ModelRequirement(
        kind=ModelRequirementKind.CONCRETE_MODEL, value=candidate[:64]
    )


def local_account_availability() -> tuple[AccountAvailability, ...]:
    """What this host can honestly say about each gateway account.

    HydraFlow is not the gateway and cannot see the gateway's upstream
    credentials; the authoritative account view is ADR-0138's
    ``GET /control/v2/accounts``. What this host *can* see is the credential the
    legacy router itself gates on, which is the only availability fact a shadow
    decision needs, and the decision records the accounts it used so the verdict
    is reconstructible. There is no administrative overlay yet (ADR-0138 §D2),
    so every account reads ``enabled``.
    """
    return (
        AccountAvailability(
            account_id=legacy_account_id(ProviderBinding.ANTHROPIC),
            provider_binding=ProviderBinding.ANTHROPIC,
            configured=True,
            administrative_state=AdministrativeState.ENABLED,
        ),
        AccountAvailability(
            account_id=legacy_account_id(ProviderBinding.ZAI_HARNESS),
            provider_binding=ProviderBinding.ZAI_HARNESS,
            configured=zai_key_present(),
            administrative_state=AdministrativeState.ENABLED,
        ),
    )


def build_route_context(
    *,
    config: HydraFlowConfig,
    principal_id: str,
    final_provider: str,
    final_model: str,
    request_face: RequestFace,
    stages: Sequence[RouteStage],
) -> RouteContext:
    """Compile one spawn's live routing facts into the resolver's pure input."""
    deciding = classify_legacy_mechanism(stages)
    binding = provider_binding_for(final_provider, final_model)
    legacy = LegacyRoute(
        provider_binding=binding,
        account_id=legacy_account_id(binding),
        model=final_model.strip()[:128],
        transport=transport_for(final_provider, request_face),
        mechanism=deciding.mechanism,
        mechanism_detail=deciding.detail,
    )
    return RouteContext(
        repo=RepoIdentity.from_canonical(str(getattr(config, "repo", "") or "")),
        repo_class=_repo_class(config),
        principal_id=principal_id.strip()[:256] or "unknown",
        worker_role=canonical_worker_role(principal_id),
        model_requirement=requirement_for_model(final_model),
        request_face=request_face,
        accounts=local_account_availability(),
        legacy_route=legacy,
    )


def compare(decision: RouteDecision, actual: LegacyRoute) -> ShadowDivergence:
    """Classify how a proposed route differs from the one that actually ran."""
    if decision.outcome is not DecisionOutcome.SELECTED:
        return ShadowDivergence.NOT_SELECTED
    provider_moved = decision.provider_binding is not actual.provider_binding
    proposed_model = (decision.effective_model or actual.model).strip().lower()
    model_moved = proposed_model != actual.model.strip().lower()
    if provider_moved and model_moved:
        return ShadowDivergence.PROVIDER_AND_MODEL
    if provider_moved:
        return ShadowDivergence.PROVIDER
    if model_moved:
        return ShadowDivergence.MODEL
    return ShadowDivergence.NONE


def record_route_shadow(
    *,
    config: HydraFlowConfig,
    principal_id: str,
    stages: Sequence[RouteStage],
    final_provider: str,
    final_model: str,
    request_face: RequestFace,
    issue_number: int | None = None,
    pr_number: int | None = None,
    now: datetime | None = None,
) -> ShadowDecision | None:
    """Record what policy would have chosen beside what legacy actually chose.

    Returns ``None`` when shadow recording is off or the sink refused the write.
    It never returns a route and never mutates one — the caller has already
    routed by the time this is called, and this function's only output is a
    durable record.
    """
    if getattr(config, "gateway_route_shadow_enabled", False) is not True:
        return None
    try:
        context = build_route_context(
            config=config,
            principal_id=principal_id,
            final_provider=final_provider,
            final_model=final_model,
            request_face=request_face,
            stages=stages,
        )
        actual = context.legacy_route
        if actual is None:  # pragma: no cover - build_route_context always sets it
            return None
        loaded = RoutingPolicyStore(policy_snapshot_path(config)).load()
        decision = explain(context, loaded.snapshot, snapshot_state=loaded.state)
        divergence = compare(decision, actual)
        record = ShadowDecision(
            recorded_at=now or datetime.now(UTC),
            principal_id=context.principal_id,
            issue_number=issue_number,
            pr_number=pr_number,
            actual=actual,
            proposed=decision,
            agreed=divergence is ShadowDivergence.NONE,
            divergence=divergence,
        )
        RoutingAuditLog(shadow_decision_log_path(config)).append(
            record.model_dump(mode="json"),
            recorded_at=record.recorded_at.isoformat(),
        )
        return record
    except Exception as exc:  # noqa: BLE001 - observation must not break a spawn
        reraise_on_credit_or_bug(exc)
        logger.warning("route-shadow: recording skipped (%s)", exc_detail(exc))
        return None


def record_agentic_route_shadow(
    *,
    config: HydraFlowConfig,
    principal_id: str,
    dial_field: str | None,
    dial_provider: str,
    after_ratchet: str,
    after_repo_provider: str,
    final_provider: str,
    final_model: str,
    issue_number: int | None = None,
    pr_number: int | None = None,
) -> ShadowDecision | None:
    """Shadow one tool-using spawn, given the provider after each legacy stage."""
    if getattr(config, "gateway_route_shadow_enabled", False) is not True:
        return None
    stages = (
        RouteStage(
            mechanism=(
                LegacyRouteMechanism.ROLE_DIAL
                if dial_field
                else LegacyRouteMechanism.DEFAULT
            ),
            provider=dial_provider or "claude",
            detail=f"{dial_field or 'default'}={dial_provider}"[:200],
        ),
        RouteStage(
            mechanism=LegacyRouteMechanism.FLEET_RATCHET,
            provider=after_ratchet or "claude",
            detail="gateway_fleet_ratchet_enabled=true",
        ),
        RouteStage(
            mechanism=LegacyRouteMechanism.REPO_PROVIDER,
            provider=after_repo_provider or "claude",
            detail=f"repo_provider={getattr(config, 'repo_provider', '')}"[:200],
        ),
        RouteStage(
            mechanism=LegacyRouteMechanism.CREDIT_FAILOVER,
            provider=final_provider or "claude",
            detail=(
                f"credit_failover_model={getattr(config, 'credit_failover_model', '')}"
            )[:200],
        ),
    )
    return record_route_shadow(
        config=config,
        principal_id=principal_id,
        stages=stages,
        final_provider=final_provider,
        final_model=final_model,
        request_face=RequestFace.AGENTIC,
        issue_number=issue_number,
        pr_number=pr_number,
    )


def record_one_shot_route_shadow(
    *,
    config: HydraFlowConfig,
    principal_id: str,
    requested_provider: str | None,
    transport_provider: str,
    model: str,
    issue_number: int | None = None,
    pr_number: int | None = None,
) -> ShadowDecision | None:
    """Shadow one lightweight spawn — the seam the per-role z.ai dials run through."""
    if getattr(config, "gateway_route_shadow_enabled", False) is not True:
        return None
    maintenance = str(getattr(config, "maintenance_provider", "claude") or "claude")
    dialled = requested_provider if requested_provider is not None else maintenance
    stages = (
        RouteStage(
            mechanism=(
                LegacyRouteMechanism.ROLE_DIAL
                if requested_provider is not None
                else LegacyRouteMechanism.MAINTENANCE_DEFAULT
            ),
            provider=dialled or "claude",
            detail=(
                f"provider={requested_provider}"
                if requested_provider is not None
                else f"maintenance_provider={maintenance}"
            )[:200],
        ),
        RouteStage(
            mechanism=LegacyRouteMechanism.FLEET_RATCHET,
            provider=transport_provider or "claude",
            detail="gateway_fleet_ratchet_enabled=true",
        ),
    )
    return record_route_shadow(
        config=config,
        principal_id=principal_id,
        stages=stages,
        final_provider=transport_provider,
        final_model=model,
        request_face=RequestFace.ONE_SHOT,
        issue_number=issue_number,
        pr_number=pr_number,
    )


def _repo_class(config: HydraFlowConfig) -> RepoClass:
    raw = str(getattr(config, "gateway_repo_class", "") or "").strip().lower()
    try:
        return RepoClass(raw)
    except ValueError:
        # An unrecognised class is not a routing input worth guessing at; the
        # most restrictive capture class is the safe reading.
        return RepoClass.PERSONAL

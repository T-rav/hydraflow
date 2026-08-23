"""Typed control-plane and observation models for the LLM gateway."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrincipalKind(StrEnum):
    """Kinds of principals that may own a virtual gateway key."""

    LOOP = "loop"
    ROLE = "role"
    SPAWN = "spawn"
    PERSON = "person"
    TEAM = "team"


class RepoClass(StrEnum):
    """Repository data classifications understood by capture policy."""

    HYDRAFLOW = "hydraflow"
    CLIENT = "client"
    PERSONAL = "personal"


class ProviderBinding(StrEnum):
    """Upstream provider a virtual key is allowed to reach."""

    ANTHROPIC = "anthropic"
    ZAI_HARNESS = "zai-harness"


LEGACY_ACCOUNT_IDS: Mapping[ProviderBinding, str] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: "legacy-anthropic",
        ProviderBinding.ZAI_HARNESS: "legacy-zai-harness",
    }
)
"""Stable, non-secret account identities compiled from the v1 env-pair upstreams.

ADR-0138. The id is derived from the *provider binding*, never from credential
material, so it is safe in URLs, ledgers, and the operator dashboard. Multi-account
pools (ADR-0138 "Later phases") add ids from a server-owned definition file; these
two remain the deterministic identity of the legacy environment pairs.
"""


def legacy_account_id(binding: ProviderBinding) -> str:
    """Return the stable account id compiled from one legacy upstream pair."""
    return LEGACY_ACCOUNT_IDS[binding]


_ZAI_MODEL_PREFIX = "glm"


def binding_for_model(model: str) -> ProviderBinding:
    """Return the upstream account a concrete model id must be served by.

    The single definition of "which lane serves this model", so the route-aware
    mint and HydraFlow's own legacy classifier cannot disagree about it. ADR-0139
    §D8 warns that two copies of one mapping is a guaranteed future disagreement;
    ``route_shadow.provider_binding_for`` delegates here for its model branch.
    """
    return (
        ProviderBinding.ZAI_HARNESS
        if model.strip().lower().startswith(_ZAI_MODEL_PREFIX)
        else ProviderBinding.ANTHROPIC
    )


class BodyCapturePolicy(StrEnum):
    """Whether request and response entities may be retained."""

    METADATA_ONLY = "metadata-only"
    FULL = "full"


class GatewayRequestStatus(StrEnum):
    """Terminal observation state for one upstream attempt."""

    COMPLETED = "completed"
    CLIENT_ABORTED = "client-aborted"
    UPSTREAM_ERROR = "upstream-error"


class Principal(BaseModel):
    """Identity stamped onto a virtual key and every resulting ledger row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PrincipalKind
    id: str = Field(min_length=1, max_length=256)
    spawn_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    # Optional work attribution: the GitHub issue / PR the spawn was working
    # on, so ledger spend can be rolled up per issue. Additive and optional.
    issue_number: int | None = Field(default=None, ge=1)
    pr_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_spawn_id_for_spawn(self) -> Principal:
        """A spawn principal must identify the concrete spawn it represents."""
        if self.kind is PrincipalKind.SPAWN and self.spawn_id is None:
            raise ValueError("spawn_id is required for a spawn principal")
        return self


class MintKeyRequest(BaseModel):
    """Public wire model for ``POST /control/v1/keys``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_kind: PrincipalKind
    principal_id: str = Field(min_length=1, max_length=256)
    spawn_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    issue_number: int | None = Field(default=None, ge=1)
    pr_number: int | None = Field(default=None, ge=1)
    repo_slug: str = Field(min_length=1, max_length=512)
    repo_class: RepoClass
    provider_binding: ProviderBinding
    capture_bodies: bool = False
    ttl_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def enforce_identity_and_capture_policy(self) -> MintKeyRequest:
        """Reject incomplete spawn identity and prohibited body capture."""
        self.principal()
        if self.repo_class is not RepoClass.HYDRAFLOW and self.capture_bodies:
            raise ValueError("body capture is prohibited for client and personal repos")
        return self

    def principal(self) -> Principal:
        """Return the structured principal carried by this wire request."""
        return Principal(
            kind=self.principal_kind,
            id=self.principal_id,
            spawn_id=self.spawn_id,
            session_id=self.session_id,
            issue_number=self.issue_number,
            pr_number=self.pr_number,
        )

    @property
    def body_capture_policy(self) -> BodyCapturePolicy:
        """Translate the wire boolean to the durable policy enum."""
        if self.capture_bodies:
            return BodyCapturePolicy.FULL
        return BodyCapturePolicy.METADATA_ONLY


class RouteBinding(BaseModel):
    """The immutable route one v2 key is bound to for its whole lifetime.

    Fixed at mint and never renegotiated: a policy edit affects the *next* key,
    never this one. ``effective_model`` is what the data plane checks every
    request body against, and the policy lineage is what makes the resulting
    ledger row joinable back to the decision that authorised it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # The gateway's own identity for the decision that authorised this lease.
    mint_decision_id: str = Field(min_length=1, max_length=128)
    # The pure resolver's content-addressed decision id (ADR-0139), echoed so a
    # ledger row joins back to the shadow chain that recorded the route.
    route_decision_id: str = Field(min_length=1, max_length=128)
    dispatch_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    effective_model: str = Field(min_length=1, max_length=128)
    policy_id: str | None = Field(default=None, max_length=64)
    policy_revision: int = Field(default=0, ge=0)
    snapshot_hash: str = Field(default="", max_length=128)
    # ADR-0142. Where in the account pool this lease landed, and how many
    # bounded-fallback hops its dispatch had spent by the time it did. Both are
    # fixed at mint like everything else here, so the ledger row a request
    # produces says which hop paid for it.
    fallback_position: int = Field(default=0, ge=0)
    fallback_hops: int = Field(default=0, ge=0)


class GatewayIdentity(BaseModel):
    """Non-secret identity resolved from a valid virtual key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    principal: Principal
    repo_slug: str
    repo_class: RepoClass
    provider_binding: ProviderBinding
    body_capture_policy: BodyCapturePolicy
    issued_at: datetime
    expires_at: datetime
    # Absent on every v1 key, which is what makes "this key is governed" a
    # structural fact rather than a claim the caller makes.
    route_binding: RouteBinding | None = None


class MintKeyResponse(BaseModel):
    """One-time virtual key material returned to the control-plane caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    token: str = Field(repr=False)
    expires_at: datetime


class RevokeKeyResponse(BaseModel):
    """Control-plane acknowledgement for explicit key revocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    revoked: bool

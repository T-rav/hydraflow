"""Route-aware resolve-and-mint for governed spawns (ADR-0141, #11539).

``POST /control/v2/keys`` takes an *identity and an intent* — which repository,
which role, which model requirement, which attempt — and returns one decision
plus, only when that decision selects, one short-lived key immutably bound to
the account and model it selected. The wire request has no ``provider_binding``
field at all: the caller cannot name an upstream, and
:func:`hydraflow_gateway.models.binding_for_model` decides which account serves
the model the policy chose.

Three invariants hold this together, and each is measured rather than asserted:

* **One attempt, one decision, at most one lease.** ``mint_attempt_id`` is the
  idempotency key. Every mutation of the attempt table and every key mint happen
  under one lock with no ``await`` between them, so two racing retries cannot
  both mint.
* **A raw token exists only on the original response path.** A replay of a
  *selected* attempt returns the decision and the key id with
  ``credential_state=withheld-replay`` and no token. The client's recourse is an
  acknowledged revoke and a new attempt, never a second hidden lease.
* **The gateway re-checks the one invariant it can check alone.** It does not
  hold the policy snapshot (ADR-0140 §D1 put that on the HydraFlow side, where
  the resolver reads it), so it does not re-derive the route. It *does* re-derive
  the account from the model, and it independently refuses a literal Opus/Sonnet
  requirement served by anything without Anthropic provenance — ADR-0139 §D4's
  guard, enforced a second time on the far side of the trust boundary.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from driver_contracts import ModelRequirement, ModelRequirementKind, WorkerRole
from hydraflow_gateway.keys import KeyPolicyError, VirtualKeyStore
from hydraflow_gateway.models import (
    BodyCapturePolicy,
    Principal,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
    RouteBinding,
    binding_for_model,
    legacy_account_id,
)
from hydraflow_gateway.routing_policy import (
    DecisionOutcome,
    RequestFace,
    canonicalize_repo,
)

GOVERNED_MINT_SCHEMA_VERSION = 1

MINTABLE_REQUEST_FACES: frozenset[RequestFace] = frozenset(
    {RequestFace.AGENTIC, RequestFace.ONE_SHOT}
)
"""``unknown`` is not a face a binding can be reasoned about, so it is refused."""

DEFAULT_MAX_TRACKED_ATTEMPTS = 10_000
"""Ceiling on the idempotency table before the mint holds rather than evicting."""


class MintRefusal(StrEnum):
    """Why the gateway would not turn one attempt into a lease."""

    LITERAL_FAMILY_UNSATISFIABLE = "literal-family-unsatisfiable"
    ACCOUNT_NOT_CONFIGURED = "account-not-configured"
    UNSUPPORTED_REQUEST_FACE = "unsupported-request-face"
    REPO_IDENTITY_NOT_CANONICAL = "repo-identity-not-canonical"
    EFFECTIVE_MODEL_MISSING = "effective-model-missing"
    MINT_CAPACITY_EXHAUSTED = "mint-capacity-exhausted"
    KEY_POLICY_REFUSED = "key-policy-refused"


class CredentialState(StrEnum):
    """What happened to the one-time token on this particular response."""

    ISSUED = "issued"
    WITHHELD_REPLAY = "withheld-replay"
    NOT_APPLICABLE = "not-applicable"


class MintAttemptConflict(ValueError):
    """One ``mint_attempt_id`` was reused for a materially different intent."""


class MintV2Request(BaseModel):
    """Public wire model for ``POST /control/v2/keys``.

    Deliberately carries no ``provider_binding``, ``account_id``, or upstream:
    ``extra="forbid"`` makes the absence a structural refusal rather than a
    documented convention.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mint_attempt_id: str = Field(min_length=1, max_length=128)
    dispatch_id: str = Field(min_length=1, max_length=128)
    principal_kind: PrincipalKind
    principal_id: str = Field(min_length=1, max_length=256)
    spawn_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    issue_number: int | None = Field(default=None, ge=1)
    pr_number: int | None = Field(default=None, ge=1)
    repo: str = Field(min_length=1, max_length=512)
    repo_slug: str = Field(min_length=1, max_length=512)
    repo_class: RepoClass
    worker_role: WorkerRole | None = None
    request_face: RequestFace
    requirement_kind: ModelRequirementKind
    requirement_value: str = Field(min_length=1, max_length=64)
    requested_model: str = Field(default="", max_length=128)
    effective_model: str = Field(min_length=1, max_length=128)
    route_decision_id: str = Field(min_length=1, max_length=128)
    policy_id: str | None = Field(default=None, max_length=64)
    policy_revision: int = Field(default=0, ge=0)
    snapshot_hash: str = Field(default="", max_length=128)
    capture_bodies: bool = False
    ttl_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def enforce_identity_and_capture_policy(self) -> MintV2Request:
        """Reject an inexpressible requirement, identity, or capture request."""
        self.requirement()
        self.principal()
        if self.repo_class is not RepoClass.HYDRAFLOW and self.capture_bodies:
            raise ValueError("body capture is prohibited for client and personal repos")
        return self

    def requirement(self) -> ModelRequirement:
        """Return the shared ADR-0137 contract this request states."""
        return ModelRequirement(
            kind=self.requirement_kind, value=self.requirement_value
        )

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

    def signature(self) -> str:
        """A canonical digest of this attempt's whole identity and intent.

        Two requests sharing a ``mint_attempt_id`` but differing anywhere else
        are two intents wearing one idempotency key, which is a conflict rather
        than a retry.
        """
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MintDecisionView(BaseModel):
    """The sanitized decision one resolve attempt produced. No credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = GOVERNED_MINT_SCHEMA_VERSION
    mint_decision_id: str
    route_decision_id: str
    mint_attempt_id: str
    dispatch_id: str
    recorded_at: datetime
    outcome: DecisionOutcome
    reason: str
    repo: str
    repo_slug: str
    worker_role: WorkerRole | None = None
    request_face: RequestFace
    requested_model: str = ""
    effective_model: str | None = None
    account_id: str | None = None
    provider_binding: ProviderBinding | None = None
    policy_id: str | None = None
    policy_revision: int = Field(default=0, ge=0)
    snapshot_hash: str = ""
    key_id: str | None = None


class MintV2Response(BaseModel):
    """One-time key material plus the decision that authorised it.

    ``token`` is present on exactly one response in an attempt's life. Every
    replay reports ``credential_state=withheld-replay`` and returns nothing a
    caller could send upstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str | None = None
    token: str | None = Field(default=None, repr=False)
    expires_at: datetime | None = None
    credential_state: CredentialState
    decision: MintDecisionView


@dataclass(frozen=True, slots=True)
class _Attempt:
    """One recorded resolve attempt: its intent digest, decision, and lease."""

    signature: str
    decision: MintDecisionView
    recorded_epoch: float


def _mint_decision_id(signature: str, outcome: DecisionOutcome, reason: str) -> str:
    payload = f"{signature}|{outcome.value}|{reason}"
    return f"gwd_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


def evaluate_attempt(
    request: MintV2Request, *, configured_bindings: frozenset[ProviderBinding]
) -> tuple[DecisionOutcome, str, ProviderBinding | None]:
    """Classify one attempt without minting anything. Pure and total.

    The gateway does not re-derive the *route* — it has no policy snapshot — so
    this answers the narrower question it can answer alone: may the model the
    policy chose be served, and by which account?
    """
    if request.request_face not in MINTABLE_REQUEST_FACES:
        return (
            DecisionOutcome.REJECTED,
            MintRefusal.UNSUPPORTED_REQUEST_FACE.value,
            None,
        )
    if canonicalize_repo(request.repo) is None:
        return (
            DecisionOutcome.REJECTED,
            MintRefusal.REPO_IDENTITY_NOT_CANONICAL.value,
            None,
        )
    effective = request.effective_model.strip()
    if not effective:
        return (
            DecisionOutcome.REJECTED,
            MintRefusal.EFFECTIVE_MODEL_MISSING.value,
            None,
        )
    requirement = request.requirement()
    # Only the literal-family arm is re-checked. A policy may legitimately map a
    # capability — or remap a concrete request — onto another model; ADR-0139 §D4
    # constrains exactly one thing, and re-deriving more than that here would be
    # the gateway inventing a second, divergent policy engine.
    if (
        requirement.kind is ModelRequirementKind.LITERAL_FAMILY
        and not requirement.satisfied_by(effective)
    ):
        return (
            DecisionOutcome.REJECTED,
            MintRefusal.LITERAL_FAMILY_UNSATISFIABLE.value,
            None,
        )
    binding = binding_for_model(effective)
    if binding not in configured_bindings:
        # An operational gap, not a policy verdict: the route is right and the
        # credential is missing, so the honest answer is hold.
        return (
            DecisionOutcome.HELD,
            MintRefusal.ACCOUNT_NOT_CONFIGURED.value,
            binding,
        )
    return DecisionOutcome.SELECTED, "matched-policy", binding


class RouteMintStore:
    """The atomic resolve/record/mint transaction for one gateway worker."""

    def __init__(
        self,
        *,
        key_store: VirtualKeyStore,
        configured_bindings: frozenset[ProviderBinding],
        wall_clock: Callable[[], float] = time.time,
        attempt_retention_seconds: int = 86_400,
        max_tracked_attempts: int = DEFAULT_MAX_TRACKED_ATTEMPTS,
    ) -> None:
        if attempt_retention_seconds <= 0:
            raise ValueError("attempt_retention_seconds must be positive")
        if max_tracked_attempts <= 0:
            raise ValueError("max_tracked_attempts must be positive")
        self._key_store = key_store
        self._configured_bindings = configured_bindings
        self._wall_clock = wall_clock
        self._attempt_retention_seconds = attempt_retention_seconds
        self._max_tracked_attempts = max_tracked_attempts
        self._attempts: dict[str, _Attempt] = {}
        self._lock = threading.Lock()

    def resolve_and_mint(self, request: MintV2Request) -> MintV2Response:
        """Record exactly one decision and, only when it selects, one key."""
        signature = request.signature()
        now = self._wall_clock()
        with self._lock:
            existing = self._attempts.get(request.mint_attempt_id)
            if existing is not None:
                return self._replay(existing, signature)
            if len(self._attempts) >= self._max_tracked_attempts:
                self._reap_locked(now)
            if len(self._attempts) >= self._max_tracked_attempts:
                return self._refused(
                    request,
                    signature,
                    now,
                    outcome=DecisionOutcome.HELD,
                    reason=MintRefusal.MINT_CAPACITY_EXHAUSTED.value,
                    binding=None,
                )
            outcome, reason, binding = evaluate_attempt(
                request, configured_bindings=self._configured_bindings
            )
            if outcome is not DecisionOutcome.SELECTED or binding is None:
                return self._refused(
                    request,
                    signature,
                    now,
                    outcome=outcome,
                    reason=reason,
                    binding=binding,
                )
            return self._mint(request, signature, now, binding=binding, reason=reason)

    def reap_expired_attempts(self) -> int:
        """Drop attempt records whose lease can no longer exist. Returns the count."""
        now = self._wall_clock()
        with self._lock:
            return self._reap_locked(now)

    # -- internals ---------------------------------------------------------

    def _reap_locked(self, now: float) -> int:
        horizon = now - self._attempt_retention_seconds
        stale = [
            attempt_id
            for attempt_id, attempt in self._attempts.items()
            if attempt.recorded_epoch <= horizon
        ]
        for attempt_id in stale:
            del self._attempts[attempt_id]
        return len(stale)

    def _replay(self, existing: _Attempt, signature: str) -> MintV2Response:
        if existing.signature != signature:
            raise MintAttemptConflict(
                "mint_attempt_id was reused for a different identity or intent"
            )
        withheld = existing.decision.outcome is DecisionOutcome.SELECTED
        return MintV2Response(
            key_id=existing.decision.key_id,
            token=None,
            expires_at=None,
            credential_state=(
                CredentialState.WITHHELD_REPLAY
                if withheld
                else CredentialState.NOT_APPLICABLE
            ),
            decision=existing.decision,
        )

    def _view(
        self,
        request: MintV2Request,
        signature: str,
        now: float,
        *,
        outcome: DecisionOutcome,
        reason: str,
        binding: ProviderBinding | None,
        key_id: str | None,
        effective_model: str | None,
    ) -> MintDecisionView:
        return MintDecisionView(
            mint_decision_id=_mint_decision_id(signature, outcome, reason),
            route_decision_id=request.route_decision_id,
            mint_attempt_id=request.mint_attempt_id,
            dispatch_id=request.dispatch_id,
            recorded_at=datetime.fromtimestamp(now, tz=UTC),
            outcome=outcome,
            reason=reason,
            repo=request.repo,
            repo_slug=request.repo_slug,
            worker_role=request.worker_role,
            request_face=request.request_face,
            requested_model=request.requested_model,
            effective_model=effective_model,
            account_id=None if binding is None else legacy_account_id(binding),
            provider_binding=binding,
            policy_id=request.policy_id,
            policy_revision=request.policy_revision,
            snapshot_hash=request.snapshot_hash,
            key_id=key_id,
        )

    def _refused(
        self,
        request: MintV2Request,
        signature: str,
        now: float,
        *,
        outcome: DecisionOutcome,
        reason: str,
        binding: ProviderBinding | None,
    ) -> MintV2Response:
        decision = self._view(
            request,
            signature,
            now,
            outcome=outcome,
            reason=reason,
            binding=binding,
            key_id=None,
            effective_model=None,
        )
        self._attempts[request.mint_attempt_id] = _Attempt(
            signature=signature, decision=decision, recorded_epoch=now
        )
        return MintV2Response(
            key_id=None,
            token=None,
            expires_at=None,
            credential_state=CredentialState.NOT_APPLICABLE,
            decision=decision,
        )

    def _mint(
        self,
        request: MintV2Request,
        signature: str,
        now: float,
        *,
        binding: ProviderBinding,
        reason: str,
    ) -> MintV2Response:
        effective = request.effective_model.strip()
        provisional = _mint_decision_id(signature, DecisionOutcome.SELECTED, reason)
        route_binding = RouteBinding(
            mint_decision_id=provisional,
            route_decision_id=request.route_decision_id,
            dispatch_id=request.dispatch_id,
            account_id=legacy_account_id(binding),
            effective_model=effective,
            policy_id=request.policy_id,
            policy_revision=request.policy_revision,
            snapshot_hash=request.snapshot_hash,
        )
        try:
            minted = self._key_store.mint_bound(
                principal=request.principal(),
                repo_slug=request.repo_slug,
                repo_class=request.repo_class,
                provider_binding=binding,
                capture_bodies=request.capture_bodies,
                ttl_seconds=request.ttl_seconds,
                route_binding=route_binding,
            )
        except KeyPolicyError as exc:
            # A TTL or capture-policy refusal is a decision, not a crash: it is
            # recorded like any other so the attempt cannot be silently retried
            # into a second lease.
            return self._refused(
                request,
                signature,
                now,
                outcome=DecisionOutcome.REJECTED,
                reason=f"{MintRefusal.KEY_POLICY_REFUSED.value}: {exc}"[:200],
                binding=binding,
            )
        decision = self._view(
            request,
            signature,
            now,
            outcome=DecisionOutcome.SELECTED,
            reason=reason,
            binding=binding,
            key_id=minted.key_id,
            effective_model=effective,
        )
        self._attempts[request.mint_attempt_id] = _Attempt(
            signature=signature, decision=decision, recorded_epoch=now
        )
        return MintV2Response(
            key_id=minted.key_id,
            token=minted.token,
            expires_at=minted.expires_at,
            credential_state=CredentialState.ISSUED,
            decision=decision,
        )

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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from driver_contracts import ModelRequirement, ModelRequirementKind, WorkerRole
from hydraflow_gateway.keys import KeyPolicyError, VirtualKeyStore
from hydraflow_gateway.models import (
    Principal,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
    RouteBinding,
    binding_for_model,
)
from hydraflow_gateway.routing_account_state import (
    AccountRuntimeState,
    AccountSelection,
    select_account,
)
from hydraflow_gateway.routing_fallback import (
    CitedDecision,
    FallbackVerdict,
    TerminalDecisionIndex,
    authorise_fallback,
    outcome_for,
)
from hydraflow_gateway.routing_policy import (
    AccountRejection,
    AccountRejectionReason,
    DecisionOutcome,
    RequestFace,
    SnapshotState,
    canonicalize_repo,
    runtime_slug_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from hydraflow_gateway.routing_account_admin import AccountAdminStore
    from hydraflow_gateway.routing_accounts import AccountPool

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
    UNBINDABLE_REQUEST_FACE = "unbindable-request-face"
    REPO_IDENTITY_NOT_CANONICAL = "repo-identity-not-canonical"
    REPO_IDENTITY_MISMATCH = "repo-identity-mismatch"
    EFFECTIVE_MODEL_MISSING = "effective-model-missing"
    MINT_CAPACITY_EXHAUSTED = "mint-capacity-exhausted"
    KEY_POLICY_REFUSED = "key-policy-refused"
    # ADR-0142. A pool turns "is this lane configured?" into three distinct
    # answers, and an operator needs to tell them apart: nothing on the lane has
    # a credential, something does but none of them may take a lease right now,
    # or the record of what an operator withdrew cannot be read at all.
    NO_ELIGIBLE_ACCOUNT = "no-eligible-account"
    ACCOUNT_STATE_UNAVAILABLE = "account-state-unavailable"
    LEASE_CAPACITY_EXHAUSTED = "lease-capacity-exhausted"


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
    # ADR-0142 bounded fallback. Both name a *prior decision of this dispatch*,
    # and neither names an account: a citation can only ever move the start of
    # the scan further down a candidate list the gateway itself computes.
    retry_of_mint_decision_id: str | None = Field(default=None, max_length=128)
    supersedes_mint_decision_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def enforce_identity_and_capture_policy(self) -> MintV2Request:
        """Reject an inexpressible requirement, identity, or capture request."""
        self.requirement()
        self.principal()
        if self.repo_class is not RepoClass.HYDRAFLOW and self.capture_bodies:
            raise ValueError("body capture is prohibited for client and personal repos")
        if (
            self.retry_of_mint_decision_id is not None
            and self.supersedes_mint_decision_id is not None
        ):
            # A hop and a replacement are opposite intents — one advances a
            # position and the other holds it — so an attempt claiming both has
            # no answer the gateway could choose on its behalf.
            raise ValueError(
                "retry_of_mint_decision_id and supersedes_mint_decision_id are "
                "mutually exclusive"
            )
        return self

    def citation(self) -> tuple[str, bool] | None:
        """The prior decision this attempt cites and whether it advances, or None."""
        if self.retry_of_mint_decision_id is not None:
            return self.retry_of_mint_decision_id, True
        if self.supersedes_mint_decision_id is not None:
            return self.supersedes_mint_decision_id, False
        return None

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
    # ADR-0142. The pool's half of "explain this decision": where in the
    # candidate order this attempt landed, how many hops the dispatch has spent,
    # and a code for every account the selection passed over.
    fallback_position: int = Field(default=0, ge=0)
    fallback_hops: int = Field(default=0, ge=0)
    rejected_accounts: tuple[AccountRejection, ...] = ()


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


def _inadmissible(request: MintV2Request) -> str | None:
    """Return why this attempt could never become a lease, or ``None``.

    Every clause here is a *rejection*: the attempt itself is malformed or
    unbindable, independently of which accounts this deployment happens to have.
    Held outcomes — where the route is right and something operational is
    missing — are decided by the caller.
    """
    if request.request_face not in MINTABLE_REQUEST_FACES:
        return MintRefusal.UNBINDABLE_REQUEST_FACE.value
    canonical = canonicalize_repo(request.repo)
    if canonical is None:
        return MintRefusal.REPO_IDENTITY_NOT_CANONICAL.value
    if runtime_slug_for(canonical) != request.repo_slug.strip().lower():
        # The request carries a repository twice: the canonical identity the
        # decision was resolved against, and the path-safe slug every downstream
        # join uses — the key record, the ledger row, the active-route views. If
        # they disagree, a governed lease is attributable to a repository the
        # decision never named, which is worse than a refusal.
        return MintRefusal.REPO_IDENTITY_MISMATCH.value
    if not request.effective_model.strip():
        return MintRefusal.EFFECTIVE_MODEL_MISSING.value
    requirement = request.requirement()
    # Only the literal-family arm is re-checked. A policy may legitimately map a
    # capability — or remap a concrete request — onto another model; ADR-0139 §D4
    # constrains exactly one thing, and re-deriving more than that here would be
    # the gateway inventing a second, divergent policy engine.
    if requirement.kind is ModelRequirementKind.LITERAL_FAMILY and (
        not requirement.satisfied_by(request.effective_model.strip())
    ):
        return MintRefusal.LITERAL_FAMILY_UNSATISFIABLE.value
    return None


def unavailable_reason(rejected: Sequence[AccountRejection]) -> str:
    """Why no account on this lane could take a lease, as one code.

    "Nothing on this lane has a credential" and "every account here is drained,
    tripped, or full" send an operator to two different places, so they are two
    codes rather than one hold with a shrug. A lane with no candidates at all
    reports the credential answer: an account that does not exist is, from the
    operator's chair, an account nobody configured.
    """
    live = [
        rejection
        for rejection in rejected
        if rejection.reason is not AccountRejectionReason.BEFORE_FALLBACK_POSITION
    ]
    if all(
        rejection.reason is AccountRejectionReason.NOT_CONFIGURED for rejection in live
    ):
        return MintRefusal.ACCOUNT_NOT_CONFIGURED.value
    return MintRefusal.NO_ELIGIBLE_ACCOUNT.value


class RouteMintStore:
    """The atomic resolve/select/record/mint transaction for one gateway worker."""

    def __init__(
        self,
        *,
        key_store: VirtualKeyStore,
        pool: AccountPool,
        account_state: AccountRuntimeState | None = None,
        admin: AccountAdminStore | None = None,
        terminals: TerminalDecisionIndex | None = None,
        max_fallback_hops: int = 1,
        wall_clock: Callable[[], float] = time.time,
        attempt_retention_seconds: int = 86_400,
        max_tracked_attempts: int = DEFAULT_MAX_TRACKED_ATTEMPTS,
    ) -> None:
        if attempt_retention_seconds <= 0:
            raise ValueError("attempt_retention_seconds must be positive")
        if max_tracked_attempts <= 0:
            raise ValueError("max_tracked_attempts must be positive")
        if max_fallback_hops < 0:
            raise ValueError("max_fallback_hops must not be negative")
        self._key_store = key_store
        self._pool = pool
        self._state = account_state or AccountRuntimeState(pool.registry)
        self._admin = admin
        self._terminals = terminals or TerminalDecisionIndex()
        self._max_fallback_hops = max_fallback_hops
        self._wall_clock = wall_clock
        self._attempt_retention_seconds = attempt_retention_seconds
        self._max_tracked_attempts = max_tracked_attempts
        self._attempts: dict[str, _Attempt] = {}
        # A second index over the same records, so a citation can be resolved by
        # the id the *caller* holds — the decision id — without scanning. It is
        # maintained and reaped with the attempt table so the two can never
        # disagree about which decisions still exist.
        self._by_decision: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def account_state(self) -> AccountRuntimeState:
        """The live capacity and circuit this store admits leases against."""
        return self._state

    @property
    def terminals(self) -> TerminalDecisionIndex:
        """The terminal-evidence index a bounded fallback is authorised from."""
        return self._terminals

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
                # Answered but NOT recorded. Recording it would consume a slot
                # in the very table that is full, so a retry loop against a
                # saturated gateway would grow the table one record per attempt
                # for a whole retention window — the unbounded growth this
                # ceiling exists to prevent, arriving through the ceiling.
                # Nothing is lost by not recording: no lease was reserved, so
                # there is no outcome a replay could need to be told about.
                return self._answer(
                    self._view(
                        request,
                        signature,
                        now,
                        outcome=DecisionOutcome.HELD,
                        reason=MintRefusal.MINT_CAPACITY_EXHAUSTED.value,
                        binding=None,
                        key_id=None,
                        effective_model=None,
                    )
                )
            return self._decide(request, signature, now)

    @property
    def tracked_attempts(self) -> int:
        """How many attempt records are retained right now. Never a credential."""
        with self._lock:
            return len(self._attempts)

    def reap_expired_attempts(self) -> int:
        """Drop attempt records whose lease can no longer exist. Returns the count."""
        now = self._wall_clock()
        with self._lock:
            return self._reap_locked(now)

    # -- internals ---------------------------------------------------------

    def _decide(
        self, request: MintV2Request, signature: str, now: float
    ) -> MintV2Response:
        """Run one attempt from admissibility to lease. Called under the lock.

        The order is the order of authority: an inadmissible attempt is refused
        before any lineage is consulted, a lineage before any live state is read,
        and the live state before anything is reserved — so a caller bug never
        presents as a transient hold a retry loop would hammer, and no attempt
        can reserve a slot it was never entitled to ask for.
        """
        refused = partial(self._refused, request, signature, now)
        rejection = _inadmissible(request)
        if rejection is not None:
            return refused(
                outcome=DecisionOutcome.REJECTED, reason=rejection, binding=None
            )
        effective = request.effective_model.strip()
        binding = binding_for_model(effective)
        verdict = self._fallback_verdict(request, effective)
        if verdict.refusal is not None:
            return refused(
                outcome=outcome_for(verdict.refusal),
                reason=verdict.refusal.value,
                binding=binding,
            )
        overlay = self._admin.read() if self._admin is not None else None
        if overlay is not None and overlay.state is SnapshotState.CORRUPT:
            # ADR-0139's rule for an unreadable policy snapshot, applied to the
            # record of what an operator withdrew: an overlay that cannot be read
            # must not be read as "nothing was withdrawn".
            return refused(
                outcome=DecisionOutcome.HELD,
                reason=MintRefusal.ACCOUNT_STATE_UNAVAILABLE.value,
                binding=binding,
            )
        selection = select_account(
            pool=self._pool,
            state=self._state,
            administrative={} if overlay is None else dict(overlay.states),
            model=effective,
            start_position=verdict.start_position,
        )
        if selection.account_id is None:
            return refused(
                outcome=DecisionOutcome.HELD,
                reason=unavailable_reason(selection.rejected),
                binding=binding,
                selection=selection,
                verdict=verdict,
            )
        return self._mint(
            request,
            signature,
            now,
            binding=binding,
            reason="matched-policy",
            selection=selection,
            verdict=verdict,
        )

    def _fallback_verdict(
        self, request: MintV2Request, effective_model: str
    ) -> FallbackVerdict:
        """Where this attempt may start scanning, given the lineage it cites."""
        citation = request.citation()
        if citation is None:
            return FallbackVerdict()
        decision_id, advance = citation
        attempt_id = self._by_decision.get(decision_id)
        attempt = None if attempt_id is None else self._attempts.get(attempt_id)
        cited = None if attempt is None else _cited_decision(attempt.decision)
        return authorise_fallback(
            cited=cited,
            evidence=self._terminals.get(decision_id),
            # The prior key must already be gone. Asked of the capacity table
            # rather than of the key store because a lease slot is exactly what a
            # successor would double-book, and the slot is released on every path
            # that ends a key: revoke, expiry, reap and shutdown.
            lease_held=(
                cited is not None
                and cited.key_id is not None
                and self._state.lease_held(cited.key_id)
            ),
            dispatch_id=request.dispatch_id,
            repo=request.repo,
            effective_model=effective_model,
            advance=advance,
            max_hops=self._max_fallback_hops,
        )

    def _reap_locked(self, now: float) -> int:
        horizon = now - self._attempt_retention_seconds
        stale = [
            attempt_id
            for attempt_id, attempt in self._attempts.items()
            if attempt.recorded_epoch <= horizon
        ]
        for attempt_id in stale:
            decision_id = self._attempts[attempt_id].decision.mint_decision_id
            del self._attempts[attempt_id]
            # Only when it still points at the record being dropped: two attempts
            # can share a decision id (the id is content-addressed over the
            # signature), and clearing the index blindly would orphan a live one.
            if self._by_decision.get(decision_id) == attempt_id:
                del self._by_decision[decision_id]
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
        account_id: str | None = None,
        selection: AccountSelection | None = None,
        verdict: FallbackVerdict | None = None,
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
            account_id=account_id,
            provider_binding=binding,
            policy_id=request.policy_id,
            policy_revision=request.policy_revision,
            snapshot_hash=request.snapshot_hash,
            key_id=key_id,
            fallback_position=_recorded_position(selection, verdict),
            fallback_hops=0 if verdict is None else verdict.hops,
            rejected_accounts=() if selection is None else selection.rejected,
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
        selection: AccountSelection | None = None,
        verdict: FallbackVerdict | None = None,
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
            selection=selection,
            verdict=verdict,
        )
        self._record(request.mint_attempt_id, signature, decision, now)
        return self._answer(decision)

    def _record(
        self,
        attempt_id: str,
        signature: str,
        decision: MintDecisionView,
        now: float,
    ) -> None:
        """Retain one attempt under both the ids it can be reached by."""
        self._attempts[attempt_id] = _Attempt(
            signature=signature, decision=decision, recorded_epoch=now
        )
        self._by_decision[decision.mint_decision_id] = attempt_id

    @staticmethod
    def _answer(decision: MintDecisionView) -> MintV2Response:
        """A decision with no lease behind it, and therefore no credential."""
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
        selection: AccountSelection,
        verdict: FallbackVerdict,
    ) -> MintV2Response:
        effective = request.effective_model.strip()
        account_id = selection.account_id or ""
        provisional = _mint_decision_id(signature, DecisionOutcome.SELECTED, reason)
        route_binding = RouteBinding(
            mint_decision_id=provisional,
            route_decision_id=request.route_decision_id,
            dispatch_id=request.dispatch_id,
            account_id=account_id,
            effective_model=effective,
            policy_id=request.policy_id,
            policy_revision=request.policy_revision,
            snapshot_hash=request.snapshot_hash,
            fallback_position=selection.position or 0,
            fallback_hops=verdict.hops,
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
                selection=selection,
                verdict=verdict,
            )
        if not self._state.reserve_lease(account_id, holder=minted.key_id):
            # Selection's capacity check is advisory (it takes and releases the
            # capacity table's own lock), and only the reservation decides. A key
            # this store cannot account for would be a lease outside the ceiling
            # for its whole TTL, so it is revoked here rather than left to expire.
            self._key_store.revoke(minted.key_id)
            return self._refused(
                request,
                signature,
                now,
                outcome=DecisionOutcome.HELD,
                reason=MintRefusal.LEASE_CAPACITY_EXHAUSTED.value,
                binding=binding,
                selection=selection,
                verdict=verdict,
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
            account_id=account_id,
            selection=selection,
            verdict=verdict,
        )
        self._record(request.mint_attempt_id, signature, decision, now)
        return MintV2Response(
            key_id=minted.key_id,
            token=minted.token,
            expires_at=minted.expires_at,
            credential_state=CredentialState.ISSUED,
            decision=decision,
        )


def _recorded_position(
    selection: AccountSelection | None, verdict: FallbackVerdict | None
) -> int:
    """Where this decision landed — the position the NEXT hop advances from.

    The position actually **selected**, not the position the scan started at. A
    scan that skipped an ineligible candidate lands further down than it began,
    and the successor computes its start as ``recorded + 1``: recording the start
    instead would make the next hop begin on the very account this decision used,
    so a "fallback" would re-select the account whose failure licensed it. A
    decision that selected nothing reports where it looked, because there is no
    landing to report and the next attempt should not skip past a candidate this
    one never took.
    """
    if selection is not None and selection.position is not None:
        return selection.position
    return 0 if verdict is None else verdict.start_position


def _cited_decision(decision: MintDecisionView) -> CitedDecision:
    """The flat lineage facts a fallback verdict needs from a recorded decision."""
    return CitedDecision(
        selected=decision.outcome is DecisionOutcome.SELECTED,
        dispatch_id=decision.dispatch_id,
        repo=decision.repo,
        effective_model=decision.effective_model or "",
        account_id=decision.account_id,
        fallback_position=decision.fallback_position,
        fallback_hops=decision.fallback_hops,
        key_id=decision.key_id,
    )

"""Pure routing-policy core: identity, precedence, and route explanation (ADR-0139).

No I/O, no clock, no credential, no global state, no exception on any input.
:func:`explain` is a **total** function from ``(context, snapshot)`` to exactly
one :class:`RouteDecision`: every failure mode — a corrupt snapshot, an
ambiguous repository identity, two policies that tie, a literal Opus request a
policy would answer with GLM — is a typed ``held``/``rejected`` outcome carrying
a reason **code**, never a raised exception. That totality is load-bearing: in
this phase the only caller is a *shadow observer* running beside a live spawn
it must never be able to disturb (see ``src/route_shadow.py``).

Three rules this module exists to make machine-checkable:

* **Canonical repository identity is exactly ``owner/repo``.** The runtime slug
  (``owner-repo``) is lossy — ``a-b/c`` and ``a/b-c`` both flatten to ``a-b-c``
  — so a slug-derived identity is marked ``legacy-lossy`` and can never satisfy
  an exact-repo policy. Ambiguity fails closed rather than guessing an owner.
* **Precedence is deterministic, and a tie is invalid.** Two enabled policies at
  the same precedence level and priority whose matches overlap and whose actions
  differ are a *conflict*: :func:`validate_policies` rejects the write, and if
  one somehow reaches the resolver the decision is ``rejected``, never
  insertion-order roulette.
* **An Anthropic request can never quietly resolve to GLM.** The predicate is
  ADR-0137's own allow-list (:func:`driver_contracts.has_anthropic_provenance`,
  behind :meth:`~driver_contracts.ModelRequirement.satisfied_by`), applied both
  to a policy's declared mapping and to the *lane*: a literal family, and a
  concrete request for an Anthropic id — the bare CLI aliases included — need an
  Anthropic account unless an operator wrote an explicit remapping. A
  provider-neutral capability resolves only through an explicit mapping.

``eligible`` lives here, inside an explanation, exactly where ADR-0138 §D2 said
it belongs — never as an account-global field.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from fnmatch import fnmatchcase
from functools import partial

from pydantic import BaseModel, ConfigDict, Field, model_validator

from driver_contracts import (
    ModelRequirement,
    ModelRequirementKind,
    WorkerRole,
    has_anthropic_provenance,
)
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, RepoClass

ROUTING_DECISION_SCHEMA_VERSION = 1
"""Bumped only on a breaking change; additive optional fields do not bump it."""

MAX_EXPLAINED_POLICIES = 200
"""Upper bound on the considerations one explanation *renders*.

Matching always evaluates the whole snapshot: truncating the candidate set
before matching would let policy #201 be silently unreachable, which is a
routing bug wearing a bounded-payload costume. Only the rendered trace is
capped, and it is capped from the most specific end, so the winner and its
nearest rivals are always the rows that survive."""

_REPO_PART = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
_CANONICAL_REPO_RE = re.compile(rf"^{_REPO_PART}/{_REPO_PART}$")

_POLICY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_ANTHROPIC_ONLY_BINDINGS = frozenset({ProviderBinding.ANTHROPIC})
"""Bindings whose accounts can serve an Anthropic model."""

CLAUDE_CLI_ALIASES = frozenset({"opus", "sonnet", "haiku"})
"""Bare aliases the Claude CLI accepts as ``--model``. They ARE Anthropic requests.

``opus`` and ``sonnet`` classify as literal families; ``haiku`` has no family in
ADR-0137's ``LITERAL_FAMILIES``, so without naming it here a ``--model haiku``
spawn would read as an ordinary concrete request and lose the Anthropic-lane
guard. Several maintenance loops still default to it."""


class RepoIdentityVersion(StrEnum):
    """Whether a repository identity is exact or was recovered from a lossy slug."""

    CANONICAL = "canonical"
    LEGACY_LOSSY = "legacy-lossy"


class RequestFace(StrEnum):
    """The shape of the upstream request a spawn will make."""

    AGENTIC = "agentic"
    ONE_SHOT = "one-shot"
    UNKNOWN = "unknown"


class RouteTransport(StrEnum):
    """How a spawn reaches its upstream, and therefore whether policy governs it."""

    GATEWAY = "gateway"
    HARNESS_DIRECT = "harness-direct"
    DIRECT_HTTP = "direct-http"


class PolicySelection(StrEnum):
    """How an account is chosen from an eligible pool."""

    ORDERED = "ordered"


class OnUnavailable(StrEnum):
    """What a policy asks for when nothing in its pool is eligible."""

    HOLD = "hold"
    REJECT = "reject"


class FallbackCondition(StrEnum):
    """Terminal outcomes that may license a *new* attempt on the next route."""

    CREDIT_EXHAUSTED = "credit_exhausted"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class PolicySource(StrEnum):
    """Where the authority for a decision came from."""

    MANAGED_POLICY = "managed-policy"
    LEGACY_COMPATIBILITY = "legacy-compatibility"
    NONE = "none"


class PrecedenceLevel(IntEnum):
    """The design's ordered precedence ladder. Lower wins."""

    SYSTEM_SAFETY = 1
    REPO_ROLE_REQUIREMENT = 2
    REPO_ROLE = 3
    REPO_ANY_ROLE = 4
    CLASS_ROLE = 5
    CLASS_DEFAULT = 6
    GLOBAL_ROLE_OR_REQUIREMENT = 7
    GLOBAL_DEFAULT = 8
    LEGACY_COMPATIBILITY = 9


class DecisionOutcome(StrEnum):
    """The three dispositions a resolve attempt may reach."""

    SELECTED = "selected"
    HELD = "held"
    REJECTED = "rejected"


class DecisionReason(StrEnum):
    """Why a decision reached its outcome, as a code rather than prose."""

    MATCHED_POLICY = "matched-policy"
    NO_POLICY_APPLIES = "no-policy-applies"
    POLICY_CONFLICT = "policy-conflict"
    SNAPSHOT_UNAVAILABLE = "snapshot-unavailable"
    LITERAL_FAMILY_UNSATISFIABLE = "literal-family-unsatisfiable"
    CAPABILITY_UNMAPPED = "capability-unmapped"
    MODEL_NOT_ALLOWED = "model-not-allowed"
    NO_ELIGIBLE_ACCOUNT = "no-eligible-account"
    NO_LEGACY_ROUTE = "no-legacy-route"


class MatchReason(StrEnum):
    """Why one policy did or did not apply to one context."""

    MATCHED = "matched"
    POLICY_DISABLED = "policy-disabled"
    REPO_NOT_IN_SET = "repo-not-in-set"
    REPO_IDENTITY_NOT_CANONICAL = "repo-identity-not-canonical"
    REPO_CLASS_NOT_IN_SET = "repo-class-not-in-set"
    ROLE_NOT_IN_SET = "role-not-in-set"
    ROLE_NOT_CANONICAL = "role-not-canonical"
    PRINCIPAL_NOT_IN_SET = "principal-not-in-set"
    REQUIREMENT_NOT_IN_SET = "requirement-not-in-set"
    REQUEST_FACE_NOT_IN_SET = "request-face-not-in-set"
    OUTRANKED = "outranked"


class AccountRejectionReason(StrEnum):
    """Why one account was not eligible for one route."""

    NOT_CONFIGURED = "not-configured"
    ADMINISTRATIVE_DRAINING = "administrative-draining"
    ADMINISTRATIVE_DISABLED = "administrative-disabled"
    PROVIDER_LOCK_MISMATCH = "provider-lock-mismatch"
    NOT_IN_POOL = "not-in-pool"
    ANTHROPIC_LANE_REQUIRED = "anthropic-lane-required"
    # ADR-0142. The three live facts a *pool* adds, each a separate code so an
    # operator reading a held decision can tell "I disabled this" from "it is
    # rate-limited" from "it is full" — three different actions.
    CIRCUIT_OPEN = "circuit-open"
    LEASE_CAPACITY_EXHAUSTED = "lease-capacity-exhausted"
    BEFORE_FALLBACK_POSITION = "before-fallback-position"


class LegacyRouteMechanism(StrEnum):
    """Which legacy dial actually chose the live route.

    None of these is a managed policy, and the explanation says so: HydraFlow
    pins several loops to z.ai through a per-role ``*_provider`` dial, and this
    phase must report that truthfully rather than dress it up as policy.
    """

    DEFAULT = "default"
    ROLE_DIAL = "role-dial"
    MAINTENANCE_DEFAULT = "maintenance-default"
    REPO_PROVIDER = "repo-provider"
    FLEET_RATCHET = "fleet-ratchet"
    CREDIT_FAILOVER = "credit-failover"


class PolicyValidationCode(StrEnum):
    """Deterministic reasons a policy set is not admissible."""

    DUPLICATE_POLICY_ID = "duplicate-policy-id"
    INVALID_POLICY_ID = "invalid-policy-id"
    NON_CANONICAL_REPO_ID = "non-canonical-repo-id"
    DUPLICATE_REQUIREMENT_MAPPING = "duplicate-requirement-mapping"
    LITERAL_FAMILY_MAPPED_TO_FOREIGN_MODEL = "literal-family-mapped-to-foreign-model"
    MAPPED_MODEL_NOT_IN_ALLOWED_PATTERNS = "mapped-model-not-in-allowed-patterns"
    EQUAL_PRECEDENCE_CONFLICT = "equal-precedence-conflict"


def canonicalize_repo(value: str) -> str | None:
    """Return the canonical lowercase ``owner/repo``, or ``None`` when ambiguous.

    Fails closed on anything that is not exactly one slash between two safe
    path segments — a bare runtime slug (``acme-project``) has no slash and is
    therefore *not* canonicalizable, which is the whole point: ``a-b/c`` and
    ``a/b-c`` produce the same slug, so recovering an owner from one would be a
    coin flip that a policy join would then treat as fact.
    """
    candidate = value.strip().lower()
    if not candidate or ".." in candidate:
        return None
    if candidate.count("/") != 1:
        return None
    if _CANONICAL_REPO_RE.fullmatch(candidate) is None:
        return None
    return candidate


def runtime_slug_for(canonical: str) -> str:
    """Return the path-safe runtime slug HydraFlow derives from a canonical id."""
    return canonical.replace("/", "-")


def canonical_worker_role(principal_id: str) -> WorkerRole | None:
    """Return the canonical :class:`WorkerRole` this principal names, or ``None``.

    Exact, case-insensitive match only — ADR-0137 owns the vocabulary and
    ADR-0138 §D6 fixed this join. A principal that is a loop name
    (``adr_reviewer``), a person, or an unmapped source stays ``None`` rather
    than being guessed into a role this resolver would then route on.
    """
    candidate = principal_id.strip().lower()
    for role in WorkerRole:
        if role.value == candidate:
            return role
    return None


class RepoIdentity(BaseModel):
    """A repository's identity plus how exactly it is known."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: RepoIdentityVersion
    canonical: str | None = None
    runtime_slug: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def _canonical_iff_exact(self) -> RepoIdentity:
        exact = self.version is RepoIdentityVersion.CANONICAL
        if exact and self.canonical is None:
            raise ValueError("a canonical identity must carry its owner/repo")
        if not exact and self.canonical is not None:
            raise ValueError("a legacy-lossy identity must not claim owner/repo")
        return self

    @classmethod
    def from_canonical(cls, value: str) -> RepoIdentity:
        """Build an identity from ``owner/repo``, degrading to lossy when ambiguous."""
        canonical = canonicalize_repo(value)
        if canonical is None:
            return cls.from_runtime_slug(value)
        return cls(
            version=RepoIdentityVersion.CANONICAL,
            canonical=canonical,
            runtime_slug=runtime_slug_for(canonical),
        )

    @classmethod
    def from_runtime_slug(cls, slug: str) -> RepoIdentity:
        """Build a deliberately un-joinable identity from the lossy runtime slug."""
        return cls(
            version=RepoIdentityVersion.LEGACY_LOSSY,
            canonical=None,
            runtime_slug=(slug.strip().lower() or "unknown")[:512],
        )


class AccountAvailability(BaseModel):
    """The pure account facts a decision needs — no credential, no health prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1, max_length=128)
    provider_binding: ProviderBinding
    configured: bool
    administrative_state: AdministrativeState = AdministrativeState.ENABLED


class LegacyRoute(BaseModel):
    """The route the authoritative legacy path actually chose for this spawn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_binding: ProviderBinding
    account_id: str = Field(min_length=1, max_length=128)
    model: str = Field(default="", max_length=128)
    transport: RouteTransport
    mechanism: LegacyRouteMechanism
    mechanism_detail: str = Field(default="", max_length=200)

    @property
    def governed(self) -> bool:
        """True when this route passes through the gateway and policy could bind it."""
        return self.transport is RouteTransport.GATEWAY


class RouteContext(BaseModel):
    """Everything a decision is a function of. Echoed into the explanation.

    An explanation that cannot be reconstructed from the inputs it names is not
    an explanation, so this whole object is carried on the record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: RepoIdentity
    repo_class: RepoClass
    principal_id: str = Field(min_length=1, max_length=256)
    worker_role: WorkerRole | None = None
    model_requirement: ModelRequirement
    request_face: RequestFace = RequestFace.UNKNOWN
    accounts: tuple[AccountAvailability, ...] = ()
    legacy_route: LegacyRoute | None = None


class RequirementMapping(BaseModel):
    """One requested requirement and the concrete model a policy answers it with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement: ModelRequirement
    effective_model: str = Field(min_length=1, max_length=128)


class RoutingMatch(BaseModel):
    """Which spawn contexts a policy claims. An empty dimension means *any*."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_ids: tuple[str, ...] = ()
    repo_classes: tuple[RepoClass, ...] = ()
    roles: tuple[WorkerRole, ...] = ()
    principal_ids: tuple[str, ...] = ()
    model_requirements: tuple[ModelRequirement, ...] = ()
    request_faces: tuple[RequestFace, ...] = ()


class RoutingAction(BaseModel):
    """What a matching policy asks for. Nothing here is enforced in this phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_lock: ProviderBinding | None = None
    account_pool: tuple[str, ...] = ()
    requirement_map: tuple[RequirementMapping, ...] = ()
    allowed_patterns: tuple[str, ...] = ()
    forbid_direct_bypass: bool = False
    selection: PolicySelection = PolicySelection.ORDERED
    on_unavailable: OnUnavailable = OnUnavailable.HOLD
    fallback_on: tuple[FallbackCondition, ...] = ()


class RoutingPolicy(BaseModel):
    """One immutable managed rule: a match, an action, and its rank."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=10_000)
    system_safety: bool = False
    """Only a rule marked here outranks an exact-project route (design §precedence)."""
    match: RoutingMatch = RoutingMatch()
    action: RoutingAction = RoutingAction()


class PolicySnapshot(BaseModel):
    """One durable, hashed revision of the whole policy set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTING_DECISION_SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    policies: tuple[RoutingPolicy, ...] = ()
    content_hash: str = ""

    @classmethod
    def empty(cls) -> PolicySnapshot:
        """The revision-0 snapshot every host starts from: no managed policy."""
        return cls(revision=0, policies=(), content_hash=hash_policies(()))


class SnapshotState(StrEnum):
    """How trustworthy the snapshot handed to the resolver is."""

    OK = "ok"
    ABSENT = "absent"
    CORRUPT = "corrupt"


class PolicyValidationIssue(BaseModel):
    """One reason a policy set may not be written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: PolicyValidationCode
    policy_id: str
    detail: str = Field(default="", max_length=200)


class PolicyConsideration(BaseModel):
    """One policy the resolver looked at, and what it decided about it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    precedence_level: PrecedenceLevel
    priority: int
    matched: bool
    reason: MatchReason


class AccountRejection(BaseModel):
    """One account the resolver refused, with the code for why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str
    reason: AccountRejectionReason


class RouteExplanation(BaseModel):
    """The self-sufficient trace behind one decision. Bounded and sanitized."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context: RouteContext
    considered: tuple[PolicyConsideration, ...] = ()
    eligible_account_ids: tuple[str, ...] = ()
    rejected_accounts: tuple[AccountRejection, ...] = ()
    conflicting_policy_ids: tuple[str, ...] = ()


class RouteDecision(BaseModel):
    """Exactly one disposition per resolve attempt, with its full explanation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTING_DECISION_SCHEMA_VERSION
    decision_id: str
    outcome: DecisionOutcome
    reason: DecisionReason
    policy_source: PolicySource
    policy_id: str | None = None
    policy_revision: int = Field(ge=0)
    snapshot_hash: str
    snapshot_state: SnapshotState
    precedence_level: PrecedenceLevel | None = None
    precedence_priority: int | None = None
    account_id: str | None = None
    provider_binding: ProviderBinding | None = None
    effective_model: str | None = None
    explanation: RouteExplanation


def hash_policies(policies: Sequence[RoutingPolicy]) -> str:
    """Return the order-independent content hash of a policy set."""
    payload = sorted(
        json.dumps(
            policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        for policy in policies
    )
    digest = hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True, slots=True)
class _MatchShape:
    """Which dimensions a policy's match actually names. Drives its rung."""

    repo: bool
    repo_class: bool
    role: bool
    requirement: bool


_PRECEDENCE_LADDER: tuple[
    tuple[Callable[[_MatchShape], bool], PrecedenceLevel], ...
] = (
    (
        lambda shape: shape.repo and shape.role and shape.requirement,
        PrecedenceLevel.REPO_ROLE_REQUIREMENT,
    ),
    (lambda shape: shape.repo and shape.role, PrecedenceLevel.REPO_ROLE),
    (lambda shape: shape.repo, PrecedenceLevel.REPO_ANY_ROLE),
    (lambda shape: shape.repo_class and shape.role, PrecedenceLevel.CLASS_ROLE),
    (lambda shape: shape.repo_class, PrecedenceLevel.CLASS_DEFAULT),
    (
        lambda shape: shape.role or shape.requirement,
        PrecedenceLevel.GLOBAL_ROLE_OR_REQUIREMENT,
    ),
)
"""The design's ordered ladder, most specific first. Order IS the precedence."""


def precedence_level(policy: RoutingPolicy) -> PrecedenceLevel:
    """Return the ladder rung a policy occupies, from the shape of its match.

    Specificity is structural, not declared: a policy cannot claim a rung it has
    not earned by naming the dimensions that rung is about.
    """
    if policy.system_safety:
        return PrecedenceLevel.SYSTEM_SAFETY
    shape = _MatchShape(
        repo=bool(policy.match.repo_ids),
        repo_class=bool(policy.match.repo_classes),
        role=bool(policy.match.roles) or bool(policy.match.principal_ids),
        requirement=bool(policy.match.model_requirements),
    )
    return next(
        (level for claims, level in _PRECEDENCE_LADDER if claims(shape)),
        PrecedenceLevel.GLOBAL_DEFAULT,
    )


def evaluate_match(policy: RoutingPolicy, context: RouteContext) -> MatchReason:
    """Return :attr:`MatchReason.MATCHED` or the first dimension that ruled it out."""
    if not policy.enabled:
        return MatchReason.POLICY_DISABLED
    return next(_match_failures(policy.match, context), MatchReason.MATCHED)


def _match_failures(
    match: RoutingMatch, context: RouteContext
) -> Iterator[MatchReason]:
    """Yield every dimension that rules this policy out, most decisive first."""
    if match.repo_ids:
        if context.repo.canonical is None:
            yield MatchReason.REPO_IDENTITY_NOT_CANONICAL
        elif context.repo.canonical not in match.repo_ids:
            yield MatchReason.REPO_NOT_IN_SET
    if match.repo_classes and context.repo_class not in match.repo_classes:
        yield MatchReason.REPO_CLASS_NOT_IN_SET
    if match.roles:
        if context.worker_role is None:
            yield MatchReason.ROLE_NOT_CANONICAL
        elif context.worker_role not in match.roles:
            yield MatchReason.ROLE_NOT_IN_SET
    if match.principal_ids and context.principal_id.strip().lower() not in {
        principal.strip().lower() for principal in match.principal_ids
    }:
        yield MatchReason.PRINCIPAL_NOT_IN_SET
    if (
        match.model_requirements
        and context.model_requirement not in match.model_requirements
    ):
        yield MatchReason.REQUIREMENT_NOT_IN_SET
    if match.request_faces and context.request_face not in match.request_faces:
        yield MatchReason.REQUEST_FACE_NOT_IN_SET


def _dimensions_overlap(left: Sequence[object], right: Sequence[object]) -> bool:
    """Two exact-set dimensions overlap when either is the universe or they intersect."""
    if not left or not right:
        return True
    return bool(set(left) & set(right))


def matches_overlap(left: RoutingMatch, right: RoutingMatch) -> bool:
    """True when some context could satisfy both matches at once."""
    return all(
        _dimensions_overlap(getattr(left, field), getattr(right, field))
        for field in (
            "repo_ids",
            "repo_classes",
            "roles",
            "principal_ids",
            "model_requirements",
            "request_faces",
        )
    )


def _literal_family_model_is_honest(mapping: RequirementMapping) -> bool:
    if mapping.requirement.kind is not ModelRequirementKind.LITERAL_FAMILY:
        return True
    return mapping.requirement.satisfied_by(mapping.effective_model)


def _model_allowed(model: str, patterns: Sequence[str]) -> bool:
    if not patterns:
        return True
    candidate = model.strip().lower()
    return any(fnmatchcase(candidate, pattern.strip().lower()) for pattern in patterns)


def validate_policies(
    policies: Sequence[RoutingPolicy],
) -> tuple[PolicyValidationIssue, ...]:
    """Return every reason this policy set may not be written. Empty means valid.

    Rejecting at write time is what keeps the resolver deterministic: an
    equal-precedence tie that disagrees has no defensible answer at read time,
    so it must never reach a snapshot in the first place.
    """
    issues: list[PolicyValidationIssue] = []
    seen: set[str] = set()
    for policy in policies:
        if _POLICY_ID_RE.fullmatch(policy.id) is None:
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.INVALID_POLICY_ID, policy_id=policy.id
                )
            )
        if policy.id in seen:
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.DUPLICATE_POLICY_ID, policy_id=policy.id
                )
            )
        seen.add(policy.id)
        issues.extend(_validate_one(policy))
    issues.extend(_validate_conflicts(policies))
    return tuple(issues)


def _validate_one(policy: RoutingPolicy) -> list[PolicyValidationIssue]:
    issues: list[PolicyValidationIssue] = []
    for repo_id in policy.match.repo_ids:
        if canonicalize_repo(repo_id) != repo_id:
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.NON_CANONICAL_REPO_ID,
                    policy_id=policy.id,
                    detail=repo_id[:200],
                )
            )
    requirements = [mapping.requirement for mapping in policy.action.requirement_map]
    if len(set(requirements)) != len(requirements):
        issues.append(
            PolicyValidationIssue(
                code=PolicyValidationCode.DUPLICATE_REQUIREMENT_MAPPING,
                policy_id=policy.id,
            )
        )
    for mapping in policy.action.requirement_map:
        if not _literal_family_model_is_honest(mapping):
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.LITERAL_FAMILY_MAPPED_TO_FOREIGN_MODEL,
                    policy_id=policy.id,
                    detail=f"{mapping.requirement.value}->{mapping.effective_model}"[
                        :200
                    ],
                )
            )
        if not _model_allowed(mapping.effective_model, policy.action.allowed_patterns):
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.MAPPED_MODEL_NOT_IN_ALLOWED_PATTERNS,
                    policy_id=policy.id,
                    detail=mapping.effective_model[:200],
                )
            )
    return issues


def _validate_conflicts(
    policies: Sequence[RoutingPolicy],
) -> list[PolicyValidationIssue]:
    issues: list[PolicyValidationIssue] = []
    enabled = [policy for policy in policies if policy.enabled]
    for index, left in enumerate(enabled):
        for right in enabled[index + 1 :]:
            if precedence_level(left) is not precedence_level(right):
                continue
            if left.priority != right.priority:
                continue
            if left.action == right.action:
                continue
            if not matches_overlap(left.match, right.match):
                continue
            issues.append(
                PolicyValidationIssue(
                    code=PolicyValidationCode.EQUAL_PRECEDENCE_CONFLICT,
                    policy_id=left.id,
                    detail=right.id[:200],
                )
            )
    return issues


def _rank(policy: RoutingPolicy) -> tuple[int, int, str]:
    return (int(precedence_level(policy)), -policy.priority, policy.id)


def anthropic_lane_required(
    requirement: ModelRequirement, mapped_model: str | None
) -> bool:
    """Whether only an Anthropic account can honestly serve this route.

    *mapped_model* is the model an **explicit** ``requirement_map`` entry chose,
    and ``None`` when the policy declared no mapping for this requirement. The
    distinction is the whole rule: only an operator writing a mapping may move
    an Anthropic request onto another lane.

    * a mapping resolved a model, so that model's own provenance decides — a
      policy mapping a request to ``glm-5.3`` has said out loud that a z.ai lane
      serves it, which is how "project X always uses z.ai" works;
    * otherwise a literal family always needs the Anthropic lane;
    * otherwise a *concrete* request for an Anthropic id — including the bare
      CLI aliases several loops still spawn with — needs it too. Passing the
      *resolved* model here instead would defeat this clause, because an
      unmapped concrete request resolves to itself: a ``--model haiku`` spawn
      under a ``provider_lock: zai-harness`` policy would be recorded as a clean
      ``selected`` on a z.ai account, the "GLM reported as a Claude model"
      hazard wearing a different hat.
    """
    if mapped_model is not None:
        return has_anthropic_provenance(mapped_model)
    if requirement.kind is ModelRequirementKind.LITERAL_FAMILY:
        return True
    if requirement.kind is ModelRequirementKind.CONCRETE_MODEL:
        candidate = requirement.value.strip().lower()
        return candidate in CLAUDE_CLI_ALIASES or has_anthropic_provenance(candidate)
    return False


def _eligible_accounts(
    context: RouteContext, action: RoutingAction, *, anthropic_required: bool
) -> tuple[tuple[AccountAvailability, ...], tuple[AccountRejection, ...]]:
    """Partition the available accounts, keeping the objects, not just their ids.

    The winning *object* is carried out rather than re-found by id afterwards:
    ``account_id`` is not declared unique, and re-scanning for the first match
    would let a rejected same-id account supply the reported binding.
    """
    pool = {account_id.strip().lower() for account_id in action.account_pool}
    eligible: list[AccountAvailability] = []
    rejected: list[AccountRejection] = []
    for account in context.accounts:
        reason = _account_rejection(
            account, action, pool=pool, anthropic_required=anthropic_required
        )
        if reason is None:
            eligible.append(account)
        else:
            rejected.append(
                AccountRejection(account_id=account.account_id, reason=reason)
            )
    if action.account_pool:
        order = {
            account_id.strip().lower(): index
            for index, account_id in enumerate(action.account_pool)
        }
        eligible.sort(key=lambda account: order[account.account_id.strip().lower()])
    else:
        eligible.sort(key=lambda account: account.account_id)
    return tuple(eligible), tuple(rejected)


def _account_rejection(
    account: AccountAvailability,
    action: RoutingAction,
    *,
    pool: set[str],
    anthropic_required: bool,
) -> AccountRejectionReason | None:
    """Return the first independent fact that rules this account out, or None."""
    return next(
        _account_failures(
            account, action, pool=pool, anthropic_required=anthropic_required
        ),
        None,
    )


def _account_failures(
    account: AccountAvailability,
    action: RoutingAction,
    *,
    pool: set[str],
    anthropic_required: bool,
) -> Iterator[AccountRejectionReason]:
    """Yield every reason this account cannot serve this route."""
    if not account.configured:
        yield AccountRejectionReason.NOT_CONFIGURED
    if account.administrative_state is AdministrativeState.DISABLED:
        yield AccountRejectionReason.ADMINISTRATIVE_DISABLED
    if account.administrative_state is AdministrativeState.DRAINING:
        yield AccountRejectionReason.ADMINISTRATIVE_DRAINING
    if (
        action.provider_lock is not None
        and account.provider_binding is not action.provider_lock
    ):
        yield AccountRejectionReason.PROVIDER_LOCK_MISMATCH
    if pool and account.account_id.strip().lower() not in pool:
        yield AccountRejectionReason.NOT_IN_POOL
    if anthropic_required and account.provider_binding not in _ANTHROPIC_ONLY_BINDINGS:
        yield AccountRejectionReason.ANTHROPIC_LANE_REQUIRED


def _mapped_model(
    requirement: ModelRequirement, action: RoutingAction
) -> tuple[str | None, DecisionReason | None] | None:
    """Resolve an explicit ``requirement_map`` entry, or None when none applies.

    The outer ``None`` means "this policy declares no mapping for this
    requirement" — distinct from an inner ``(None, reason)``, which means the
    mapping exists and is refused.
    """
    for mapping in action.requirement_map:
        if mapping.requirement != requirement:
            continue
        if not _literal_family_model_is_honest(mapping):
            return None, DecisionReason.LITERAL_FAMILY_UNSATISFIABLE
        if not _model_allowed(mapping.effective_model, action.allowed_patterns):
            return None, DecisionReason.MODEL_NOT_ALLOWED
        return mapping.effective_model, None
    return None


def _effective_model(
    context: RouteContext, action: RoutingAction
) -> tuple[str | None, DecisionReason | None]:
    """Resolve the model a policy would serve, or the code for why it cannot."""
    requirement = context.model_requirement
    mapped = _mapped_model(requirement, action)
    if mapped is not None:
        return mapped
    if requirement.kind is ModelRequirementKind.CONCRETE_MODEL:
        if not _model_allowed(requirement.value, action.allowed_patterns):
            return None, DecisionReason.MODEL_NOT_ALLOWED
        return requirement.value, None
    if requirement.kind is ModelRequirementKind.CAPABILITY:
        # A provider-neutral capability is meaningless without a policy saying
        # which approved model answers it. Guessing is how "high-reasoning"
        # silently becomes whatever the cheapest lane happens to serve.
        return None, DecisionReason.CAPABILITY_UNMAPPED
    # A literal family with no mapping leaves the model to the account's own
    # default; the binding check in _eligible_accounts already refused any
    # non-Anthropic lane, so this cannot become GLM.
    return None, None


def _decision_id(fields: dict[str, object]) -> str:
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return f"dec_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


def _build(
    *,
    context: RouteContext,
    snapshot: PolicySnapshot,
    snapshot_state: SnapshotState,
    outcome: DecisionOutcome,
    reason: DecisionReason,
    policy_source: PolicySource,
    explanation: RouteExplanation,
    policy_id: str | None = None,
    level: PrecedenceLevel | None = None,
    priority: int | None = None,
    account_id: str | None = None,
    provider_binding: ProviderBinding | None = None,
    effective_model: str | None = None,
) -> RouteDecision:
    identity = _decision_id(
        {
            "context": context.model_dump(mode="json"),
            "snapshot_hash": snapshot.content_hash,
            "snapshot_state": snapshot_state.value,
            "revision": snapshot.revision,
            "outcome": outcome.value,
            "reason": reason.value,
            "policy_id": policy_id,
            "account_id": account_id,
            "effective_model": effective_model,
        }
    )
    return RouteDecision(
        decision_id=identity,
        outcome=outcome,
        reason=reason,
        policy_source=policy_source,
        policy_id=policy_id,
        policy_revision=snapshot.revision,
        snapshot_hash=snapshot.content_hash,
        snapshot_state=snapshot_state,
        precedence_level=level,
        precedence_priority=priority,
        account_id=account_id,
        provider_binding=provider_binding,
        effective_model=effective_model,
        explanation=explanation,
    )


def explain(
    context: RouteContext,
    snapshot: PolicySnapshot,
    *,
    snapshot_state: SnapshotState = SnapshotState.OK,
) -> RouteDecision:
    """Return the one decision this context and snapshot imply. Never raises.

    ``held`` and ``rejected`` are answers, not errors: a corrupt snapshot holds,
    an equal-precedence tie rejects, a literal family a policy would answer with
    a foreign model rejects, and a capability with no mapping holds. When no
    managed policy claims the context, the caller's legacy route is reported as
    ``selected`` with source ``legacy-compatibility`` — the truth about how the
    spawn is actually routed, not a pretence that policy chose it.
    """
    if snapshot_state is SnapshotState.CORRUPT:
        return _build(
            context=context,
            snapshot=snapshot,
            snapshot_state=snapshot_state,
            outcome=DecisionOutcome.HELD,
            reason=DecisionReason.SNAPSHOT_UNAVAILABLE,
            policy_source=PolicySource.NONE,
            explanation=RouteExplanation(context=context),
        )

    ranked = sorted(snapshot.policies, key=_rank)
    considerations: list[PolicyConsideration] = []
    winners: list[RoutingPolicy] = []
    for policy in ranked:
        reason = evaluate_match(policy, context)
        matched = reason is MatchReason.MATCHED
        if matched and winners and _rank(winners[0])[:2] < _rank(policy)[:2]:
            matched, reason = False, MatchReason.OUTRANKED
        considerations.append(
            PolicyConsideration(
                policy_id=policy.id,
                precedence_level=precedence_level(policy),
                priority=policy.priority,
                matched=matched,
                reason=reason,
            )
        )
        if matched:
            winners.append(policy)
    considerations = considerations[:MAX_EXPLAINED_POLICIES]

    if not winners:
        return _legacy_decision(
            context=context,
            snapshot=snapshot,
            snapshot_state=snapshot_state,
            considerations=tuple(considerations),
        )

    conflicting = [policy for policy in winners if policy.action != winners[0].action]
    if conflicting:
        return _build(
            context=context,
            snapshot=snapshot,
            snapshot_state=snapshot_state,
            outcome=DecisionOutcome.REJECTED,
            reason=DecisionReason.POLICY_CONFLICT,
            policy_source=PolicySource.MANAGED_POLICY,
            level=precedence_level(winners[0]),
            priority=winners[0].priority,
            explanation=RouteExplanation(
                context=context,
                considered=tuple(considerations),
                conflicting_policy_ids=tuple(
                    sorted({winners[0].id, *(policy.id for policy in conflicting)})
                ),
            ),
        )

    return _policy_decision(
        context=context,
        snapshot=snapshot,
        snapshot_state=snapshot_state,
        policy=winners[0],
        considerations=tuple(considerations),
    )


def _legacy_decision(
    *,
    context: RouteContext,
    snapshot: PolicySnapshot,
    snapshot_state: SnapshotState,
    considerations: tuple[PolicyConsideration, ...],
) -> RouteDecision:
    legacy = context.legacy_route
    explanation = RouteExplanation(context=context, considered=considerations)
    if legacy is None:
        return _build(
            context=context,
            snapshot=snapshot,
            snapshot_state=snapshot_state,
            outcome=DecisionOutcome.HELD,
            reason=DecisionReason.NO_LEGACY_ROUTE,
            policy_source=PolicySource.NONE,
            explanation=explanation,
        )
    return _build(
        context=context,
        snapshot=snapshot,
        snapshot_state=snapshot_state,
        outcome=DecisionOutcome.SELECTED,
        reason=DecisionReason.NO_POLICY_APPLIES,
        policy_source=PolicySource.LEGACY_COMPATIBILITY,
        level=PrecedenceLevel.LEGACY_COMPATIBILITY,
        priority=0,
        account_id=legacy.account_id,
        provider_binding=legacy.provider_binding,
        effective_model=legacy.model or None,
        explanation=explanation,
    )


def _policy_decision(
    *,
    context: RouteContext,
    snapshot: PolicySnapshot,
    snapshot_state: SnapshotState,
    policy: RoutingPolicy,
    considerations: tuple[PolicyConsideration, ...],
) -> RouteDecision:
    # The model is resolved first because it decides which lanes can honestly
    # serve the route: an explicit mapping to a GLM id licenses a z.ai account,
    # while an unmapped Anthropic request does not.
    mapped = _mapped_model(context.model_requirement, policy.action)
    model, model_failure = _effective_model(context, policy.action)
    eligible, rejected = _eligible_accounts(
        context,
        policy.action,
        anthropic_required=anthropic_lane_required(
            context.model_requirement, None if mapped is None else mapped[0]
        ),
    )
    decide = partial(
        _build,
        context=context,
        snapshot=snapshot,
        snapshot_state=snapshot_state,
        policy_source=PolicySource.MANAGED_POLICY,
        policy_id=policy.id,
        level=precedence_level(policy),
        priority=policy.priority,
        explanation=RouteExplanation(
            context=context,
            considered=considerations,
            eligible_account_ids=tuple(account.account_id for account in eligible),
            rejected_accounts=rejected,
        ),
    )
    if model_failure is DecisionReason.CAPABILITY_UNMAPPED:
        return decide(outcome=DecisionOutcome.HELD, reason=model_failure)
    if model_failure is not None:
        return decide(outcome=DecisionOutcome.REJECTED, reason=model_failure)
    if not eligible:
        lane_blocked = any(
            rejection.reason is AccountRejectionReason.ANTHROPIC_LANE_REQUIRED
            for rejection in rejected
        )
        return decide(
            outcome=(
                DecisionOutcome.HELD
                if policy.action.on_unavailable is OnUnavailable.HOLD
                else DecisionOutcome.REJECTED
            ),
            reason=(
                DecisionReason.LITERAL_FAMILY_UNSATISFIABLE
                if lane_blocked
                else DecisionReason.NO_ELIGIBLE_ACCOUNT
            ),
        )
    # The winning object, not a re-lookup by id: account ids are not declared
    # unique, and re-scanning would let a rejected same-id account supply the
    # binding this decision reports.
    chosen = eligible[0]
    return decide(
        outcome=DecisionOutcome.SELECTED,
        reason=DecisionReason.MATCHED_POLICY,
        account_id=chosen.account_id,
        provider_binding=chosen.provider_binding,
        effective_model=model,
    )


def explain_batch(
    contexts: Iterable[RouteContext],
    snapshot: PolicySnapshot,
    *,
    snapshot_state: SnapshotState = SnapshotState.OK,
) -> tuple[RouteDecision, ...]:
    """Explain many contexts against ONE snapshot revision.

    The shared snapshot is the point: an effective-route matrix whose rows were
    resolved against different revisions is not a matrix, it is a race.
    """
    return tuple(
        explain(context, snapshot, snapshot_state=snapshot_state)
        for context in contexts
    )

"""Shared IssueDriver / Fable-director contracts (ADR-0137, issue #11533).

Frozen, ``extra="forbid"``, schema-versioned control contracts consumed
unchanged by the deterministic ``IssueDriver`` (#11535) and the shadow-mode
director/broker (#11537). This module is a **pure contract + admission
engine**: no I/O, no config object, no runtime wiring — the same shape as
:mod:`queue_strategy`. Importing it changes no pipeline behaviour.

Ten contracts are fixed here, in the order issue #11533 names them:

1. :class:`WorkerRole`            — the code-owned role vocabulary
2. :class:`ModelRequirement`      — what tier a worker needs (never a raw model id)
3. :class:`DriverLease` /
   :class:`WriterLease`           — issue ownership fence + single-writer fence
4. :class:`DirectorCapsule`       — the bounded canonical context a turn receives
5. :class:`DirectorCommand`       — the only thing a director turn may emit
6. :class:`WorkerDispatchRequest` — one requested child
7. :class:`WorkerReceipt`         — the typed outcome of one child
8. :class:`DriverCheckpoint`      — the durable boundary record
9. :class:`WorkerLineage`         — parent-driver → child-spawn provenance
10. :data:`WORKER_CATALOG`        — the code-owned catalog (:class:`WorkerCatalogEntry`)

The admission decision is :func:`admit_dispatch`, a pure function returning a
:class:`RejectionReason` or ``None``. Every rejection is a deterministic reason
code, never a free-form string, so receipts are machine-comparable across the
shadow-mode and canary phases.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

DRIVER_CONTRACTS_SCHEMA_VERSION = 1
"""Bumped only on a breaking change; additive optional fields do not bump it."""

MAX_DISPATCH_BATCH = 4
"""Hard ceiling on children a single director turn may request (proposal §fan-out)."""

MAX_CAPSULE_RECEIPTS = 20
"""Hard ceiling on prior receipts carried into a capsule (bounded context)."""


class DriverPhase(StrEnum):
    """The live pipeline topology (ADR-0107): Triage → Plan → Implement → Review → HITL.

    ``DISCOVER`` and ``SHAPE`` are deliberately absent — ADR-0107 collapsed them
    into planner-invoked helpers, and :data:`models.DriverState` has carried an
    11-state literal without them since. Re-adding a member here is the drift
    ``tests/regressions/test_issue_11533_stale_driver_states.py`` pins against.
    """

    TRIAGE = "TRIAGE"
    PLAN = "PLAN"
    IMPLEMENT = "IMPLEMENT"
    REVIEW = "REVIEW"
    HITL = "HITL"


class WorkerRole(StrEnum):
    """Roles a director may request. It cannot invent one outside this set."""

    EXPLORER = "explorer"
    PLANNER = "planner"
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    DEBUGGER = "debugger"
    TEST_ADEQUACY = "test_adequacy"
    REVIEWER = "reviewer"


class ModelRequirementKind(StrEnum):
    """How a worker's model tier is expressed on the wire."""

    LITERAL_FAMILY = "literal_family"
    CAPABILITY = "capability"
    CONCRETE_MODEL = "concrete_model"


LITERAL_FAMILIES = frozenset({"claude-opus", "claude-sonnet"})
"""Literal families MUST resolve to an actual Anthropic model of that family."""

CAPABILITY_CLASSES = frozenset({"high-reasoning", "balanced"})
"""Provider-neutral classes a policy may satisfy with any approved backend."""

LITERAL_FAMILY_TOKENS = {"claude-opus": "opus", "claude-sonnet": "sonnet"}
"""Family value -> the token a served model id must carry to satisfy it."""

_ANTHROPIC_MODEL_ID = re.compile(r"^(?:[a-z]{2,8}\.anthropic\.|anthropic\.)?claude-")
"""Allow-list for a served model's provenance.

Matches the first-party form (``claude-sonnet-4-6``) and the Bedrock forms,
including cross-region inference profiles (``anthropic.claude-...``,
``us.anthropic.claude-...``, ``global.anthropic.claude-...``, ``jp.anthropic...``).
A region prefix is accepted only when followed by ``anthropic.``, so a
third-party id wearing a short prefix (``zai.claude-sonnet-9``) cannot slip
through. This is deliberately an allow-list: a deny-list of known third-party vendors is fail-open the moment a
new backend ships, which is precisely the failure mode ADR-0137's own tool-surface
finding (F2) condemns. Do not reintroduce one as the primary check.
"""

NON_ANTHROPIC_MODEL_MARKERS = frozenset({"glm", "qwen", "deepseek", "kimi"})
"""Redundant belt over the allow-list, not the primary defence.

The named hazard from the proposal: *"a GLM model is never reported as
Sonnet."* :class:`WorkerReceipt` enforces this at the receipt boundary so a
mis-resolution is a validation error, not a silent relabel.
"""


class WriteScope(StrEnum):
    """What a role may touch. Only ``ISSUE_WORKTREE`` can take the writer lease."""

    NONE = "none"
    READ_ONLY_SNAPSHOT = "read_only_snapshot"
    ISSUE_WORKTREE = "issue_worktree"


class DirectorCommandKind(StrEnum):
    """The only three things a director turn may ask for."""

    DISPATCH_WORKERS = "dispatch_workers"
    YIELD = "yield"
    FINISH = "finish"


class WorkerTransport(StrEnum):
    """How a child was actually launched. Recorded on every receipt."""

    BROKERED = "brokered"
    NATIVE_TASK = "native_task"


class ReceiptStatus(StrEnum):
    """Terminal disposition of one dispatch request."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class RejectionReason(StrEnum):
    """Deterministic rejection codes. Never a free-form message."""

    STOP_FENCE = "stop_fence"
    DRAINING = "draining"
    DRIVER_IDENTITY_MISMATCH = "driver_identity_mismatch"
    STALE_EPOCH = "stale_epoch"
    STALE_PHASE_ATTEMPT = "stale_phase_attempt"
    LEASE_EXPIRED = "lease_expired"
    LIVE_LABEL_CHANGED = "live_label_changed"
    ROLE_NOT_IN_CATALOG = "role_not_in_catalog"
    ROLE_PHASE_FORBIDDEN = "role_phase_forbidden"
    ROLE_NOT_IN_CAPSULE = "role_not_in_capsule"
    MODEL_REQUIREMENT_UNSATISFIABLE = "model_requirement_unsatisfiable"
    ROUTE_POLICY_REVISION_STALE = "route_policy_revision_stale"
    DUPLICATE_IDEMPOTENCY_KEY = "duplicate_idempotency_key"
    WRITER_LEASE_HELD = "writer_lease_held"
    SELF_REVIEW_FORBIDDEN = "self_review_forbidden"
    FANOUT_OVERFLOW = "fanout_overflow"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SANDBOX_UNVERIFIED = "sandbox_unverified"

    # Added by #11541, when dispatch stopped being hypothetical. Both describe
    # failures that cannot occur while nothing is dispatched, which is why
    # neither existed before. Additive members only: the schema version gates
    # consumers of the *shape*, and no field changed.
    ROUTE_UNAVAILABLE = "route_unavailable"
    """No route or credential could be obtained for an otherwise legal request.

    The gateway was unreachable, minted nothing, or **held** the route because
    something it needs is missing — an account with no credential, a capability
    class with no mapping. The request itself was admissible, so a caretaker
    retry is the correct response once whatever is missing is supplied.

    Distinct from :attr:`ROUTE_POLICY_REVISION_STALE`, which means the director
    worked from a routing view that had moved, and from
    :attr:`MODEL_REQUIREMENT_UNSATISFIABLE`, which means the request was
    inadmissible and retrying it will never succeed. The remedy for a hold may
    be a *policy* edit rather than a gateway one — an earlier draft of this
    docstring said "look at the gateway rather than the policy", which was
    right about the outage case and wrong about every other hold.
    """

    WORKER_TIMEOUT = "worker_timeout"
    """A wall-clock budget ran out. Either the child outlived its own and was
    reaped with its process group, or the batch's **shared** budget was already
    spent when this request came up, so it was refused rather than started with
    no time to run — in which case no child existed, nothing was reaped, and
    nothing was billed. Both are the same fact for an operator (the work did not
    fit in the time allowed) and the receipt's ``lineage`` tells them apart: a
    child that ran has one.

    Deliberately not folded into :attr:`BUDGET_EXHAUSTED`, which counts a
    *USD* budget a director may not spend against: an operator reading a spike
    in one of these needs to know whether the fleet ran out of money or a
    worker ran out of time, and one counter cannot say both.
    """

    CANARY_SLOT_HELD = "canary_slot_held"
    """Another issue holds this repository's single brokered-Plan slot.

    Its own code rather than :attr:`FANOUT_OVERFLOW`, which counts a *role*
    exceeding its concurrency: folding the two together would make the canary's
    "one active Fable-directed issue per repository" bound unreadable in the
    evidence it is supposed to be proved by.
    """


def has_anthropic_provenance(served_model: str) -> bool:
    """True when *served_model*'s id is an Anthropic one by the allow-list.

    The provenance half of :meth:`ModelRequirement.satisfied_by`, exposed on its
    own so the routing resolver (ADR-0139 D4) can ask the same question of a
    *concrete-model* request without re-deriving the allow-list. Two copies of
    "is this an Anthropic model" is exactly how a third-party backend ends up
    satisfying one of them and not the other.

    This deliberately does NOT accept the Claude CLI's bare aliases
    (``opus``/``sonnet``/``haiku``): those are request shorthand, never a
    *served* model id, and widening this predicate would let a served model
    literally named ``opus`` pass as Anthropic.
    """
    served = served_model.strip().lower()
    if not _ANTHROPIC_MODEL_ID.match(served):
        return False
    return not any(marker in served for marker in NON_ANTHROPIC_MODEL_MARKERS)


class ModelRequirement(BaseModel):
    """A ``{kind, value}`` pair. Colon-joined forms are display shorthand only.

    A director never supplies a raw credential or an arbitrary model id; the
    broker resolves the requirement to a concrete model and route.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ModelRequirementKind
    value: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _value_matches_kind(self) -> ModelRequirement:
        if self.kind is ModelRequirementKind.LITERAL_FAMILY:
            if self.value not in LITERAL_FAMILIES:
                raise ValueError(
                    f"literal_family must be one of {sorted(LITERAL_FAMILIES)}, "
                    f"got {self.value!r}"
                )
        elif (
            self.kind is ModelRequirementKind.CAPABILITY
            and self.value not in CAPABILITY_CLASSES
        ):
            raise ValueError(
                f"capability must be one of {sorted(CAPABILITY_CLASSES)}, "
                f"got {self.value!r}"
            )
        return self

    def satisfied_by(self, served_model: str) -> bool:
        """True when *served_model* legitimately satisfies this requirement.

        A literal family is satisfied only by an id with Anthropic provenance
        (:data:`_ANTHROPIC_MODEL_ID`) that carries the family token and no
        third-party marker. This is the single predicate behind the "GLM is
        never reported as Sonnet" invariant, and it is an allow-list so a new
        third-party backend cannot satisfy a literal family by default.

        A concrete-model requirement is satisfied only by that exact id.
        """
        served = served_model.lower()
        if self.kind is ModelRequirementKind.LITERAL_FAMILY:
            if not has_anthropic_provenance(served):
                return False
            return LITERAL_FAMILY_TOKENS[self.value] in served
        if self.kind is ModelRequirementKind.CONCRETE_MODEL:
            return served == self.value.lower()
        return True


class WorkerCatalogEntry(BaseModel):
    """One code-owned role definition. A director selects from these; it cannot edit them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: WorkerRole
    allowed_phases: frozenset[DriverPhase]
    write_scope: WriteScope
    default_model: ModelRequirement
    max_concurrency: int = Field(ge=1, le=8)
    independent_of_implementer: bool = False
    """True for roles that must never share lineage with the implementer (review)."""

    @model_validator(mode="after")
    def _write_scope_is_coherent(self) -> WorkerCatalogEntry:
        if (
            self.independent_of_implementer
            and self.write_scope is WriteScope.ISSUE_WORKTREE
        ):
            raise ValueError(
                f"role {self.role} claims implementer-independence but requests "
                "worktree write scope; an independent reviewer cannot be a writer"
            )
        return self


def _literal(value: str) -> ModelRequirement:
    return ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value=value)


WORKER_CATALOG: dict[WorkerRole, WorkerCatalogEntry] = {
    entry.role: entry
    for entry in (
        WorkerCatalogEntry(
            role=WorkerRole.EXPLORER,
            allowed_phases=frozenset({DriverPhase.PLAN, DriverPhase.IMPLEMENT}),
            write_scope=WriteScope.READ_ONLY_SNAPSHOT,
            default_model=_literal("claude-sonnet"),
            max_concurrency=3,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.PLANNER,
            allowed_phases=frozenset({DriverPhase.PLAN}),
            write_scope=WriteScope.NONE,
            default_model=_literal("claude-sonnet"),
            max_concurrency=1,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.ARCHITECT,
            allowed_phases=frozenset({DriverPhase.PLAN, DriverPhase.REVIEW}),
            write_scope=WriteScope.NONE,
            default_model=_literal("claude-opus"),
            max_concurrency=1,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.IMPLEMENTER,
            allowed_phases=frozenset({DriverPhase.IMPLEMENT}),
            write_scope=WriteScope.ISSUE_WORKTREE,
            default_model=_literal("claude-sonnet"),
            max_concurrency=1,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.DEBUGGER,
            allowed_phases=frozenset({DriverPhase.IMPLEMENT, DriverPhase.REVIEW}),
            write_scope=WriteScope.ISSUE_WORKTREE,
            default_model=ModelRequirement(
                kind=ModelRequirementKind.CAPABILITY, value="high-reasoning"
            ),
            max_concurrency=1,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.TEST_ADEQUACY,
            allowed_phases=frozenset({DriverPhase.REVIEW}),
            write_scope=WriteScope.NONE,
            default_model=_literal("claude-opus"),
            max_concurrency=1,
        ),
        WorkerCatalogEntry(
            role=WorkerRole.REVIEWER,
            allowed_phases=frozenset({DriverPhase.REVIEW}),
            write_scope=WriteScope.NONE,
            default_model=_literal("claude-opus"),
            max_concurrency=1,
            independent_of_implementer=True,
        ),
    )
}
"""The seven proposal roles. A request for a role absent here is rejected."""


class DriverLease(BaseModel):
    """Issue ownership fence. Every director and broker action validates it.

    Recovery increments ``epoch``, which fences a stale parent and any late
    worker result carrying the old epoch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    repo_slug: str = Field(min_length=3, max_length=140)
    issue_number: int = Field(gt=0)
    phase: DriverPhase
    expected_stage_label: str = Field(min_length=1, max_length=64)
    phase_attempt: int = Field(ge=0)
    expires_at: AwareDatetime

    def is_expired(self, now: datetime) -> bool:
        """Expiry is evaluated at admission, never at construction.

        Constructing an expired lease must stay legal so a historical lease can
        be deserialized for audit and replay (#11533 B6 write-ordering replay).
        """
        return now >= self.expires_at


class WriterLease(BaseModel):
    """Single-writer fence over the issue's one canonical worktree.

    At most one write-capable worker holds this at a time. Read-only explorers
    and judges never acquire it (:class:`WorkerCatalogEntry.write_scope`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    holder_request_id: str | None = None
    worktree_base_digest: str = Field(min_length=1, max_length=128)
    worktree_head_digest: str = Field(min_length=1, max_length=128)

    @property
    def is_held(self) -> bool:
        return self.holder_request_id is not None


class WorkerLineage(BaseModel):
    """Parent-driver → child-spawn provenance. Present on every receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    parent_spawn_id: str | None = None
    child_spawn_id: str = Field(min_length=1, max_length=128)
    depth: int = Field(ge=1, le=2)
    """Depth 1 = director's own child. Depth 2 is the ceiling; no deeper nesting in v1."""


class WorkerDispatchRequest(BaseModel):
    """One child a director asks for. The broker resolves route and credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    phase_attempt: int = Field(ge=0)
    worker_role: WorkerRole
    model_requirement: ModelRequirement
    task_contract: str = Field(min_length=1, max_length=8000)
    reason: str = Field(min_length=1, max_length=2000)
    expected_route_policy_revision: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    requesting_spawn_id: str | None = Field(default=None, max_length=128)
    """The spawn whose lineage this request originates from, when there is one.

    Load-bearing for the self-review fence: admission compares this against the
    known implementer spawns, because ``request_id`` is minted fresh by the
    director and lives in a different namespace from a spawn id.
    """

    @model_validator(mode="after")
    def _director_never_names_a_concrete_model(self) -> WorkerDispatchRequest:
        if self.model_requirement.kind is ModelRequirementKind.CONCRETE_MODEL:
            raise ValueError(
                "a dispatch request may name a literal family or a capability "
                "class only; resolving to a concrete model id is the broker's job"
            )
        return self


class DirectorCommand(BaseModel):
    """The single structured value a director turn may emit.

    Free-form reasoning may explain a decision but never causes a side effect:
    only ``dispatch_workers`` / ``yield`` / ``finish`` are actionable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    kind: DirectorCommandKind
    dispatches: tuple[WorkerDispatchRequest, ...] = ()
    rationale: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def _dispatches_match_kind(self) -> DirectorCommand:
        if self.kind is DirectorCommandKind.DISPATCH_WORKERS:
            if not self.dispatches:
                raise ValueError("dispatch_workers command carries no dispatches")
            if len(self.dispatches) > MAX_DISPATCH_BATCH:
                raise ValueError(
                    f"dispatch batch of {len(self.dispatches)} exceeds "
                    f"MAX_DISPATCH_BATCH={MAX_DISPATCH_BATCH}"
                )
            keys = [d.idempotency_key for d in self.dispatches]
            if len(set(keys)) != len(keys):
                raise ValueError("duplicate idempotency_key within one dispatch batch")
            request_ids = [d.request_id for d in self.dispatches]
            if len(set(request_ids)) != len(request_ids):
                # request_id keys the writer-lease holder check, so a duplicate
                # would let two dispatches both read as the lease holder.
                raise ValueError("duplicate request_id within one dispatch batch")
        elif self.dispatches:
            raise ValueError(f"{self.kind} command must not carry dispatches")
        return self


class DirectorCapsule(BaseModel):
    """The bounded canonical context one director turn receives.

    Every turn gets enough to reconstruct from scratch, because resume is never
    guaranteed (probe P3: a dead ``--resume`` exits 1 with empty stdout). No
    ambient secrets, no raw provider keys, no unbounded repository dump.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    lease: DriverLease
    issue_goal: str = Field(min_length=1, max_length=8000)
    live_stage_label: str = Field(min_length=1, max_length=64)
    pr_number: int | None = None
    ci_state: str | None = Field(default=None, max_length=64)
    worktree_base_digest: str | None = Field(default=None, max_length=128)
    worktree_head_digest: str | None = Field(default=None, max_length=128)
    allowed_roles: frozenset[WorkerRole] = frozenset()
    route_policy_revision: str = Field(min_length=1, max_length=64)
    remaining_usd_budget: float = Field(ge=0.0)
    remaining_wall_clock_seconds: int = Field(ge=0)
    prior_receipts: tuple[WorkerReceipt, ...] = ()
    stop_requested: bool = False
    draining: bool = False

    @model_validator(mode="after")
    def _bounded_and_catalogued(self) -> DirectorCapsule:
        if len(self.prior_receipts) > MAX_CAPSULE_RECEIPTS:
            raise ValueError(
                f"capsule carries {len(self.prior_receipts)} receipts, "
                f"exceeding MAX_CAPSULE_RECEIPTS={MAX_CAPSULE_RECEIPTS}"
            )
        unknown = self.allowed_roles - set(WORKER_CATALOG)
        if unknown:
            raise ValueError(
                f"capsule advertises uncatalogued roles: {sorted(unknown)}"
            )
        return self


class WorkerReceipt(BaseModel):
    """The typed outcome of one dispatch. The unit of evidence for every gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    status: ReceiptStatus
    reason_code: RejectionReason | None = None
    lineage: WorkerLineage | None = None
    worker_role: WorkerRole
    transport: WorkerTransport = WorkerTransport.BROKERED
    requested_model: ModelRequirement
    served_model: str | None = Field(default=None, max_length=128)
    route_policy_revision: str = Field(min_length=1, max_length=64)
    artifact_digest: str | None = Field(default=None, max_length=128)
    output_contract_ok: bool | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    usd_cost: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _receipt_is_self_consistent(self) -> WorkerReceipt:
        if self.status is ReceiptStatus.ACCEPTED:
            if self.reason_code is not None:
                raise ValueError(
                    "accepted receipt must not carry a rejection reason_code"
                )
            if self.lineage is None:
                raise ValueError("accepted receipt must carry lineage")
            if self.served_model is None:
                raise ValueError("accepted receipt must record the served model")
        elif self.reason_code is None:
            raise ValueError(
                f"{self.status} receipt must carry a deterministic reason_code"
            )

        # Model honesty is checked on EVERY receipt that names a served model,
        # not only accepted ones: an expired or superseded worker still ran, and
        # its receipt is still evidence. Guarding only the accepted branch left
        # a smuggling path for a mis-resolved model.
        if self.served_model is not None and not self.requested_model.satisfied_by(
            self.served_model
        ):
            raise ValueError(
                f"served model {self.served_model!r} does not satisfy requested "
                f"{self.requested_model.kind}={self.requested_model.value!r}; "
                "a literal family must never be served by another provider's model"
            )
        return self


class DriverCheckpoint(BaseModel):
    """The durable boundary record. Ownership is never rebuilt from a transcript.

    ``vendor_session_id`` is a cache hint for ``--resume`` only; it is neither
    HydraFlow's factory session id nor a claim of ownership.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIVER_CONTRACTS_SCHEMA_VERSION
    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    last_committed_phase: DriverPhase
    committed_stage_label: str = Field(min_length=1, max_length=64)
    capsule_digest: str = Field(min_length=1, max_length=128)
    outstanding_request_ids: tuple[str, ...] = ()
    receipts: tuple[WorkerReceipt, ...] = ()
    vendor_session_id: str | None = Field(default=None, max_length=128)
    rotation_reason: str | None = Field(default=None, max_length=200)


DirectorCapsule.model_rebuild()


def admit_dispatch(
    request: WorkerDispatchRequest,
    *,
    lease: DriverLease,
    now: datetime,
    live_stage_label: str,
    route_policy_revision: str,
    writer_lease: WriterLease,
    sandbox_verified: bool,
    allowed_roles: frozenset[WorkerRole],
    seen_idempotency_keys: frozenset[str] = frozenset(),
    in_flight_for_role: int = 0,
    remaining_usd_budget: float = 0.0,
    stop_requested: bool = False,
    draining: bool = False,
    implementer_spawn_ids: frozenset[str] = frozenset(),
) -> RejectionReason | None:
    """Pure admission decision for one dispatch. ``None`` means admit.

    Ordering is deliberate and fail-closed: global stop/drain fences first, then
    the sandbox assertion, then ownership fencing, then live-label coherence,
    then catalog legality and integrity fences, then capacity. The first matching reason wins so the code is deterministic and
    replayable — the same inputs always yield the same reason.

    ``sandbox_verified`` and ``allowed_roles`` are required arguments with no
    defaults on purpose. The first carries ADR-0137's S4 observed-boundary
    assertion and the second the capsule's role allow-list; a caller that
    forgets either must fail loudly rather than dispatch fail-open.

    When admitting a *batch*, the caller folds each admitted request into
    ``seen_idempotency_keys`` and ``in_flight_for_role`` before evaluating the
    next one — this function judges one request against a fixed snapshot and
    does no accumulation of its own.
    """
    entry = WORKER_CATALOG.get(request.worker_role)

    # Rule order is the contract, so it is expressed as data rather than as
    # control flow: global stop/drain fences, then the sandbox assertion, then
    # ownership fencing, then live-label coherence, then catalog membership.
    fencing: tuple[tuple[bool, RejectionReason], ...] = (
        (stop_requested, RejectionReason.STOP_FENCE),
        (draining, RejectionReason.DRAINING),
        (not sandbox_verified, RejectionReason.SANDBOX_UNVERIFIED),
        (
            request.driver_id != lease.driver_id,
            RejectionReason.DRIVER_IDENTITY_MISMATCH,
        ),
        (request.epoch != lease.epoch, RejectionReason.STALE_EPOCH),
        (
            request.phase_attempt != lease.phase_attempt,
            RejectionReason.STALE_PHASE_ATTEMPT,
        ),
        (lease.is_expired(now), RejectionReason.LEASE_EXPIRED),
        (
            live_stage_label != lease.expected_stage_label,
            RejectionReason.LIVE_LABEL_CHANGED,
        ),
        (entry is None, RejectionReason.ROLE_NOT_IN_CATALOG),
    )
    for rejected, reason in fencing:
        if rejected:
            return reason

    if entry is None:  # pragma: no cover — narrowed by ROLE_NOT_IN_CATALOG above
        return RejectionReason.ROLE_NOT_IN_CATALOG

    # An independent reviewer may not originate from the implementer's lineage;
    # review must be a fresh external process. The comparison is on the
    # requesting SPAWN id, not on request_id — a request_id is minted fresh by
    # the director and could never collide with a spawn id, which would leave
    # this fence permanently unreachable. A write-capable role may proceed only
    # if it already holds the single-writer lease.
    self_review = (
        entry.independent_of_implementer
        and request.requesting_spawn_id is not None
        and request.requesting_spawn_id in implementer_spawn_ids
    )
    # Writer-lease checks apply only to roles that can actually take the lease.
    # A read-only explorer must not be blocked because the lease has not been
    # re-minted at the current epoch, and a lease lagging its driver's epoch is
    # a stale fence rather than ownership theft — so it reports LEASE_EXPIRED,
    # not DRIVER_IDENTITY_MISMATCH, which B5's bar counts as a theft event.
    needs_writer_lease = entry.write_scope is WriteScope.ISSUE_WORKTREE
    writer_foreign = needs_writer_lease and writer_lease.driver_id != lease.driver_id
    writer_stale = needs_writer_lease and writer_lease.epoch != lease.epoch
    writer_conflict = (
        needs_writer_lease
        and writer_lease.is_held
        and writer_lease.holder_request_id != request.request_id
    )
    legality: tuple[tuple[bool, RejectionReason], ...] = (
        (lease.phase not in entry.allowed_phases, RejectionReason.ROLE_PHASE_FORBIDDEN),
        (
            request.worker_role not in allowed_roles,
            RejectionReason.ROLE_NOT_IN_CAPSULE,
        ),
        (self_review, RejectionReason.SELF_REVIEW_FORBIDDEN),
        (
            request.expected_route_policy_revision != route_policy_revision,
            RejectionReason.ROUTE_POLICY_REVISION_STALE,
        ),
        (
            request.idempotency_key in seen_idempotency_keys,
            RejectionReason.DUPLICATE_IDEMPOTENCY_KEY,
        ),
        (writer_foreign, RejectionReason.DRIVER_IDENTITY_MISMATCH),
        (writer_stale, RejectionReason.LEASE_EXPIRED),
        (writer_conflict, RejectionReason.WRITER_LEASE_HELD),
        (in_flight_for_role >= entry.max_concurrency, RejectionReason.FANOUT_OVERFLOW),
        (remaining_usd_budget <= 0.0, RejectionReason.BUDGET_EXHAUSTED),
    )
    for rejected, reason in legality:
        if rejected:
            return reason

    return None

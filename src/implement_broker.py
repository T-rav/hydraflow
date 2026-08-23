"""The brokered Implement canary's decision layer (#11542, ADR-0137 P4).

#11541 armed dispatch for one repository at one phase, and left the writer
lease carrying the literal string ``"unobserved"`` because a shadow turn
inspects no worktree. This module is the half of #11542 that decides *whether a
boundary is inside the canary*, *what a fenced writer is allowed to be about*,
and *whether a result that came back is still admissible*. The half that starts
a child and measures a worktree is :mod:`implement_worker_runner`.

Everything here is pure, so it lives on the same side of
``tests/architecture/test_director_no_authority.py``'s decision-path list that
:mod:`plan_broker` does: no spawn, no label, no convergence write. That split
is what lets the one module that can reach a process stay the one module that
is seam-declared.

Five separable decisions live here.

**The bound.** :func:`implement_canary_covers` is the only predicate that says
an IMPLEMENT boundary is inside the canary, and it demands the same three
clauses #11541's does over a **separate** dial. Separate rather than a widening
because "widen one role boundary at a time" is the epic's rollout rule: one
dial covering both phases would mean an operator running the Plan canary today
woke up dispatching writers tomorrow.

**The fence.** :func:`check_worker_fence` is the predicate the whole phase is
named after. A fenced worker holds authority over one bounded slice — one
driver, one epoch, one phase attempt, one label, one branch, one base SHA, one
HEAD, one diff — and :func:`check_worker_fence` is what makes a result from
outside that slice *rejected* rather than merely ignored. Epoch and
phase-attempt fencing already exist from #11535 and are **reused**, not
re-derived: this adds the four worktree tokens ADR-0137 left as ``"unobserved"``
and orders them behind the ownership tokens that already existed.

**The measurement.** :data:`WORKTREE_PROBES` names the git reads a lease is
minted from and :func:`worktree_state_from_reads` turns their output into a
:class:`WorktreeState`. Split that way for the reason ``workspace_gc_loop``
splits its landed proof: the parse and the digest are pure and unit-testable,
and exactly one module runs a subprocess.

**The single writer.** :class:`WriterLeaseRegistry` holds "exactly one writer
lease exists" as a fence rather than as a convention. Read-only evidence roles
never touch it, which is the whole of "read-only evidence workers may fan out;
parallel writers remain forbidden".

**Hibernation.** :func:`hibernation_reason` names the three waits ADR-0137's C6
already releases *capacity* for — CI, diagnostic, and a human — and applies the
same rule to *authority*: a driver parked on one of them has no business
holding a writer lease, and the correct number of workers running against its
worktree is zero.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from driver_contracts import (
    WORKER_CATALOG,
    DriverPhase,
    RejectionReason,
    WorkerRole,
    WriterLease,
    WriteScope,
)
from hydraflow_gateway.routing_policy import canonicalize_repo
from plan_broker import (
    PlanRouteDecision,
    PlanRouteReason,
    resolve_worker_model,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from config import HydraFlowConfig
    from driver_contracts import DriverLease, WorkerDispatchRequest

CANARY_PHASE = DriverPhase.IMPLEMENT
"""The one phase this canary may dispatch into. #11543 widens it, not a config."""

UNMEASURED_DIGEST = "unmeasured"
"""What a worktree token reads as when the probe could not answer.

The same discipline ``fable_director.UNOBSERVED_DIGEST`` established: a token
that could not be measured says so rather than carrying a plausible-looking
sha. :func:`check_worker_fence` treats it as *unverified*, never as
*unchanged*, which is ADR-0137 S4's rule applied to a second boundary.
"""


class FenceBreach(StrEnum):
    """Why a fenced worker's result is inadmissible. ``NONE`` means it is not.

    Ordered as a vocabulary rather than as control flow, for the reason
    ``admit_dispatch``'s rule table is: first match wins, and the code an
    operator reads off a receipt must be reproducible from the inputs alone.
    """

    NONE = "none"
    DRIVER_REPLACED = "driver_replaced"
    """Another driver owns the issue. Ownership theft, not staleness."""

    EPOCH_SUPERSEDED = "epoch_superseded"
    """The driver recovered; this worker was briefed by the incarnation before."""

    PHASE_ATTEMPT_SUPERSEDED = "phase_attempt_superseded"
    """A later attempt at the same phase has started. This result is a lap behind."""

    LIVE_LABEL_CHANGED = "live_label_changed"
    """The issue left the stage the worker was briefed on — an operator drag."""

    UNMEASURED = "unmeasured"
    """A worktree token could not be measured, on either side of the run."""

    BRANCH_MISMATCH = "branch_mismatch"
    """The worktree is on a different branch — reused for another issue."""

    BASE_MOVED = "base_moved"
    """The branch was rebased or reset; the diff is against a base that is gone."""

    HEAD_MOVED = "head_moved"
    """A commit landed while the worker ran."""

    DIFF_DIGEST_STALE = "diff_digest_stale"
    """Uncommitted content changed under the worker without a commit landing."""


#: Which deterministic rejection code each breach reports on the receipt.
#: A table rather than branches so the mapping is one thing an operator can
#: read, and so a new :class:`FenceBreach` fails loudly here
#: (``FENCE_REJECTIONS[...]`` raises) rather than defaulting to a plausible one.
FENCE_REJECTIONS: dict[FenceBreach, RejectionReason] = {
    FenceBreach.DRIVER_REPLACED: RejectionReason.DRIVER_IDENTITY_MISMATCH,
    FenceBreach.EPOCH_SUPERSEDED: RejectionReason.STALE_EPOCH,
    FenceBreach.PHASE_ATTEMPT_SUPERSEDED: RejectionReason.STALE_PHASE_ATTEMPT,
    FenceBreach.LIVE_LABEL_CHANGED: RejectionReason.LIVE_LABEL_CHANGED,
    FenceBreach.UNMEASURED: RejectionReason.WORKTREE_UNMEASURED,
    FenceBreach.BRANCH_MISMATCH: RejectionReason.BRANCH_MISMATCH,
    FenceBreach.BASE_MOVED: RejectionReason.WORKTREE_DIGEST_STALE,
    FenceBreach.HEAD_MOVED: RejectionReason.WORKTREE_DIGEST_STALE,
    FenceBreach.DIFF_DIGEST_STALE: RejectionReason.WORKTREE_DIGEST_STALE,
}


class Hibernation(StrEnum):
    """Which wait a driver is parked on. ``None`` from the predicate means none."""

    CI_WAIT = "ci_wait"
    DIAGNOSTIC = "diagnostic"
    HITL_WAIT = "hitl_wait"


#: Driver state -> the wait it represents. Keyed on the driver's *post-boundary*
#: state rather than on the phase, because the phase says what just ran and the
#: state says what the issue is now doing — and it is the second that decides
#: whether a writer should exist. ``PARKED`` is ADR-0137's barrier state, whose
#: documented reasons include ``ci_wait``; ``DIAGNOSE`` is the diagnostic
#: sub-state; ``HITL_WAIT`` is the one that waits longest.
HIBERNATION_STATES: dict[str, Hibernation] = {
    "PARKED": Hibernation.CI_WAIT,
    "DIAGNOSE": Hibernation.DIAGNOSTIC,
    "HITL_WAIT": Hibernation.HITL_WAIT,
}


@dataclass(frozen=True, slots=True)
class WorktreeState:
    """The four tokens a writer lease is minted against, measured together.

    Measured *together* on purpose: a base read taken a second after a HEAD
    read describes a tree that never existed, and a fence built from two
    moments cannot say which of them the worker saw.
    """

    branch: str
    base_sha: str
    head_sha: str
    diff_digest: str

    @property
    def measured(self) -> bool:
        """True when every token is a real reading rather than a stated absence."""
        return all(
            token and token != UNMEASURED_DIGEST
            for token in (self.branch, self.base_sha, self.head_sha, self.diff_digest)
        )

    @classmethod
    def unmeasured(cls) -> WorktreeState:
        """A state that says out loud that nothing could be read."""
        return cls(
            branch=UNMEASURED_DIGEST,
            base_sha=UNMEASURED_DIGEST,
            head_sha=UNMEASURED_DIGEST,
            diff_digest=UNMEASURED_DIGEST,
        )


WORKTREE_PROBE_TOKENS: tuple[str, ...] = ("status", "base", "diff")
"""The reads one measurement takes, in the order :func:`worktree_probes` emits.

Named in the pure module so the *set* of facts a lease is minted from is
reviewable without reading the module that runs them, and so a test can pin the
probe list rather than whatever a runner happens to do.
"""


def worktree_probes(base_ref: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The git reads one measurement takes, as ``(token, argv)`` pairs.

    *base_ref* is passed rather than assumed because ``@{upstream}`` is not a
    fence: a worktree whose branch has never been pushed has no upstream, and a
    probe that silently answered nothing there would mint an unmeasured lease
    at exactly the moment a first implement attempt runs. The caller names the
    base branch it actually merges against.

    ``status --porcelain=v2 --branch`` carries the branch name and the HEAD
    object in one read, which is why it is one probe and not two — two reads
    are two moments, and a fence built from two moments cannot say which of
    them a worker saw. ``diff HEAD`` covers tracked working-tree content as
    well as the index, so a worker's own uncommitted edits move the token.
    """
    return (
        ("status", ("status", "--porcelain=v2", "--branch")),
        ("base", ("merge-base", "HEAD", base_ref)),
        ("diff", ("diff", "HEAD")),
    )


_STATUS_HEAD_PREFIX = "# branch.oid "
_STATUS_BRANCH_PREFIX = "# branch.head "


def worktree_state_from_reads(reads: Mapping[str, str]) -> WorktreeState:
    """Turn raw probe output into a :class:`WorktreeState`. Pure and total.

    Total for the same reason the tier resolver is: this runs on a live dispatch
    path, and an exception raised while measuring a fence would be a routing
    incident rather than a refusal an operator can read. A probe that answered
    nothing yields :data:`UNMEASURED_DIGEST` in its token, and
    :func:`check_worker_fence` refuses on that rather than treating a blank as
    a match — a fence whose two sides are both empty strings would otherwise
    verify perfectly and mean nothing.

    The *diff* token is hashed rather than stored: it is a fence, not a patch,
    and a receipt is evidence rather than a store.
    """
    branch = UNMEASURED_DIGEST
    head = UNMEASURED_DIGEST
    for line in (reads.get("status") or "").splitlines():
        if line.startswith(_STATUS_HEAD_PREFIX):
            head = line[len(_STATUS_HEAD_PREFIX) :].strip() or UNMEASURED_DIGEST
        elif line.startswith(_STATUS_BRANCH_PREFIX):
            branch = line[len(_STATUS_BRANCH_PREFIX) :].strip() or UNMEASURED_DIGEST
    base_raw = (reads.get("base") or "").strip()
    diff_raw = reads.get("diff")
    return WorktreeState(
        branch=branch,
        base_sha=base_raw or UNMEASURED_DIGEST,
        head_sha=head,
        # An *empty* diff is a real, common reading — a clean worktree — so it
        # must digest to a real value. Only a missing probe is unmeasured.
        diff_digest=(
            UNMEASURED_DIGEST if diff_raw is None else worktree_diff_digest(diff_raw)
        ),
    )


def worktree_diff_digest(diff: str) -> str:
    """The content-addressed token for one worktree's uncommitted-and-committed diff."""
    return f"sha256:{hashlib.sha256(diff.encode('utf-8')).hexdigest()[:32]}"


def check_worker_fence(
    *,
    minted: WorktreeState,
    observed: WorktreeState,
    lease: DriverLease,
    driver_id: str,
    driver_epoch: int,
    driver_phase_attempt: int,
    live_stage_label: str,
) -> FenceBreach:
    """Whether a fenced worker's result is still admissible. First match wins.

    The ordering is the contract and it is deliberate. Ownership comes first,
    because a result belonging to another driver is not a stale result but a
    misrouted one, and reporting it as a moved digest would put an ownership
    event into the counter ADR-0137 B5 reads as ordinary churn. Then the two
    fences #11535 already owns — epoch and phase attempt — reused here rather
    than re-derived, so a driver that recovered mid-run fences its own late
    worker with the token it already had. Then the live label, which is the
    operator's escape hatch. Only then the four worktree tokens, ordered
    coarsest-first so the reported breach is the actionable one: a reused
    worktree needs a different fix from a commit landing under a worker.

    ``UNMEASURED`` is checked before any comparison for ADR-0137 S4's reason:
    an absent reading must read as *unverified*, never as *unchanged*.
    Otherwise two unmeasured sides would compare equal and a fence that
    measured nothing would verify everything.
    """
    ownership: tuple[tuple[bool, FenceBreach], ...] = (
        (driver_id != lease.driver_id, FenceBreach.DRIVER_REPLACED),
        (driver_epoch != lease.epoch, FenceBreach.EPOCH_SUPERSEDED),
        (
            driver_phase_attempt != lease.phase_attempt,
            FenceBreach.PHASE_ATTEMPT_SUPERSEDED,
        ),
        (
            bool(live_stage_label) and live_stage_label != lease.expected_stage_label,
            FenceBreach.LIVE_LABEL_CHANGED,
        ),
        (not minted.measured or not observed.measured, FenceBreach.UNMEASURED),
        (minted.branch != observed.branch, FenceBreach.BRANCH_MISMATCH),
        (minted.base_sha != observed.base_sha, FenceBreach.BASE_MOVED),
        (minted.head_sha != observed.head_sha, FenceBreach.HEAD_MOVED),
        (minted.diff_digest != observed.diff_digest, FenceBreach.DIFF_DIGEST_STALE),
    )
    return next(
        (breach for breached, breach in ownership if breached), FenceBreach.NONE
    )


class WriterLeaseRegistry:
    """At most one write-capable worker holds one worktree at a time.

    In-memory and per-run for the reason ``PlanCanaryLatch`` is: a durable
    holder would outlive the process that took it and wedge the worktree until
    an operator noticed, while a registry that is empty after a restart is also
    telling the truth — no worker is running.

    Keyed on the **issue**, because the issue is what owns a worktree
    (``config.workspace_path_for_issue``). A global single writer would be a
    throughput regression dressed as a fence: two issues have two worktrees and
    a writer in each races nothing.

    The registry does not decide *whether* a role needs the lease — that is
    ``WorkerCatalogEntry.write_scope``, and :func:`needs_writer_lease` reads it
    so the question is answered by the catalog in one place.
    """

    def __init__(self) -> None:
        self._holders: dict[int, str] = {}

    def holder(self, issue_number: int) -> str | None:
        """The request currently holding *issue_number*'s worktree, if any."""
        return self._holders.get(issue_number)

    def acquire(self, issue_number: int, request_id: str) -> bool:
        """Take the lease, or report that another request holds it.

        Re-acquiring is idempotent for the current holder: a retry of the same
        request within one batch is the same logical writer, and refusing it
        would make a single writer look like two.
        """
        held = self._holders.get(issue_number)
        if held is not None and held != request_id:
            return False
        self._holders[issue_number] = request_id
        return True

    def release(self, issue_number: int, request_id: str) -> None:
        """Free the lease, if *request_id* is the one holding it."""
        if self._holders.get(issue_number) == request_id:
            del self._holders[issue_number]

    def revoke(self, issue_number: int) -> str | None:
        """Free the lease whoever holds it, returning the holder it displaced.

        The authority half of ADR-0137 C6: when a driver hibernates or is
        stopped, its worker's authority ends immediately rather than at the end
        of a batch nobody is watching. Returning the displaced holder is what
        lets the caller record that a revocation happened rather than guessing.
        """
        return self._holders.pop(issue_number, None)


def needs_writer_lease(role: WorkerRole) -> bool:
    """Whether *role* writes to the issue worktree and so takes the single lease.

    Read off ``WORKER_CATALOG`` rather than listed, so the registry and
    ``admit_dispatch``'s own writer-lease arm cannot disagree about which roles
    are writers. Two copies would drift the first time a role's write scope
    changed, and the drift would present as a worker admitted by one fence and
    refused by the other.
    """
    entry = WORKER_CATALOG.get(role)
    return entry is not None and entry.write_scope is WriteScope.ISSUE_WORKTREE


def implement_roles_for_implement_phase() -> frozenset[WorkerRole]:
    """The catalogued roles legal at ``IMPLEMENT``: explorer, implementer, debugger.

    Derived from ``WORKER_CATALOG`` for the same reason
    ``plan_broker.plan_roles_for_plan_phase`` is: the canary's menu and the
    admission rule table must not be able to disagree about what an IMPLEMENT
    boundary may ask for.
    """
    return frozenset(
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases
    )


def implement_canary_repo(config: HydraFlowConfig) -> str | None:
    """The one canonical repository the Implement canary is armed for, or ``None``."""
    raw = str(getattr(config, "fable_implement_canary_repo", "") or "")
    return canonicalize_repo(raw)


def implement_canary_armed(config: HydraFlowConfig) -> bool:
    """Whether the dial names a repository at all. The one-action switch.

    Read per boundary rather than captured at construction, so clearing the
    dial disarms on the **next** boundary with no restart — the live-badge
    honesty rule ``settings_registry`` enforces, and the reason a canary switch
    an operator has to restart the factory to use is not a canary switch.
    """
    return implement_canary_repo(config) is not None


def implement_canary_covers(
    config: HydraFlowConfig, *, phase: DriverPhase | None
) -> bool:
    """Whether this exact boundary is inside the Implement canary's bound.

    All three clauses, each load-bearing in a different direction:

    1. the dial is armed at all — the off-switch, and the reason an operator
       who armed only the Plan canary dispatches no writers;
    2. this repository's canonical identity is exactly the dialled one — the
       bound, and the reason a lossy slug can never match (ADR-0139 D2's
       refusal, reused in both directions);
    3. the phase is ``IMPLEMENT`` — the reason review and HITL stay Classic
       without a second guard anywhere else, which is #11542's seventh
       acceptance criterion held as a property of one function.
    """
    armed = implement_canary_repo(config)
    if armed is None:
        return False
    if phase is not CANARY_PHASE:
        return False
    return canonicalize_repo(str(getattr(config, "repo", "") or "")) == armed


def resolve_implement_model(
    request: WorkerDispatchRequest,
    *,
    phase: DriverPhase,
    route_policy_revision: str,
) -> PlanRouteDecision:
    """Resolve one Implement dispatch's model tier.

    The IMPLEMENT binding of ``plan_broker.resolve_worker_model``: the same
    code-owned tier tables, the same content-addressed decision record, the
    same "a literal family resolves literally or refuses", over this phase's
    role set and refusal vocabulary. Sharing the resolver is the point — a
    second copy would carry a second answer to "which id is ``claude-opus``",
    and the whole reason that table is code-owned is that there must be one.
    It is also why #11657's correction to the capability fence — check the
    family the table resolved to, never the incoming requirement, because
    ``satisfied_by`` returns True unconditionally for a ``CAPABILITY`` — arrived
    here without being found a second time. That matters more at IMPLEMENT than
    at PLAN: the catalogued **debugger** asks for ``high-reasoning``, so the
    capability arm is the one this phase's correction workers actually take.
    """
    return resolve_worker_model(
        request,
        phase=phase,
        canary_phase=CANARY_PHASE,
        legal_roles=implement_roles_for_implement_phase(),
        phase_refusal=PlanRouteReason.PHASE_NOT_IMPLEMENT,
        role_refusal=PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_IMPLEMENT,
        route_policy_revision=route_policy_revision,
    )


def hibernation_reason(driver_state: str) -> Hibernation | None:
    """Which wait *driver_state* is parked on, or ``None`` when it is working.

    #11542's fourth acceptance criterion — *"CI, diagnostic, and HITL waits
    hibernate the director and reconstruct from deterministic checkpoints"* —
    as a predicate rather than as three scattered checks. Keyed on the driver's
    own post-boundary state, which is the fact that decides whether a writer
    should exist at all.

    Hibernating is not an error and produces no failure: the capsule the next
    live boundary builds is reconstructed from live state exactly as every
    capsule is, and the lease it mints is measured fresh. That is what
    "reconstruct from deterministic checkpoints" means in a runtime that never
    resumes a session — there is nothing to carry across the wait, which is why
    a wait costs nothing to come back from.
    """
    return HIBERNATION_STATES.get(driver_state)


def writer_lease_for(
    lease: DriverLease, state: WorktreeState, *, holder_request_id: str | None = None
) -> WriterLease:
    """Mint the single-writer lease for *lease*'s driver at *state*'s digests.

    The one place a :class:`driver_contracts.WriterLease` is built with real
    measurements, replacing ``fable_director._unheld_writer_lease``'s
    ``"unobserved"`` placeholders for boundaries inside the canary. The
    identity and epoch come from the driver's own lease rather than from
    anywhere else, because a writer lease at a different epoch is exactly what
    ``admit_dispatch`` reports as ``LEASE_EXPIRED``.
    """
    return WriterLease(
        driver_id=lease.driver_id,
        epoch=lease.epoch,
        holder_request_id=holder_request_id,
        worktree_base_digest=state.base_sha,
        worktree_head_digest=state.head_sha,
    )

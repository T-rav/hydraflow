"""Revision-safe policy mutation with a write-ahead journal (ADR-0140).

ADR-0139 made the policy snapshot durable, hashed, and atomically replaced, and
said out loud that it exposed no way to write one. This module is that way, and
it adds exactly two things to what already existed — **concurrency** and
**provenance** — rather than a second persistence path beside them.

The property being protected is stated once and tested three ways:

* **A concurrent reader never sees a half-written revision.** Every write still
  goes through :func:`file_util.atomic_write`, so a reader holds either the
  previous coherent revision or the next one.
* **A refused edit leaves the previous revision byte-identical.** Every check —
  stale revision, scope, existence, validation — happens *before* the journal is
  written and long before the snapshot is replaced. There is no partial write to
  undo because there is never a partial write.
* **A mutation and its audit append are one transaction.** A crash between them
  is the only window, and a single-slot write-ahead journal closes it: recovery
  either finishes the append the crash cut off, or records that the intent never
  landed and leaves the prior revision authoritative.

Two scoping rules make a repository-scoped editor safe on a shared snapshot:

* it may only create, edit, or disable a policy whose match is **exactly this
  repository** — a class rule, a global rule, a system-safety rule, or a rule
  naming somebody else's repository is rendered but never written;
* a **rollback is scoped the same way**. Restoring a whole prior snapshot would
  let a repo editor silently revert an inherited rule it is not allowed to touch,
  so a rollback replaces this repository's policies with the target revision's
  and leaves every inherited policy exactly where it is.

Rollback reads its target from the audit chain — the chain *is* the durable
revision history, which is why an unverifiable chain refuses every mutation
rather than being rolled back onto.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from file_util import atomic_write, file_lock
from hydraflow_gateway.routing_audit import (
    AuditChainError,
    AuditRecord,
    ChainVerification,
    RoutingAuditLog,
)
from hydraflow_gateway.routing_policy import (
    PolicySnapshot,
    PolicyValidationIssue,
    RoutingPolicy,
    SnapshotState,
    canonicalize_repo,
    hash_policies,
    validate_policies,
)
from hydraflow_gateway.routing_store import (
    POLICY_SNAPSHOT_FILENAME,
    RoutingPolicyStore,
    SnapshotLoad,
)
from secret_scrub import scan_for_secrets

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

POLICY_JOURNAL_FILENAME = "policy-journal.json"
"""Single-slot write-ahead intent. At most one transaction is ever open."""

POLICY_MUTATION_LOCK_FILENAME = "policy-mutation.lock"
"""Advisory lock file serialising the read-modify-write across processes."""

POLICY_AUDIT_FILENAME = "policy-audit.jsonl"
"""The mutation chain. Distinct from the per-spawn shadow decision chain."""

MUTATION_RECORD_KIND = "policy-mutation"

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500

_MUTATION_LOCK_TIMEOUT_SECONDS = 10.0
"""Bounded: a policy write is an interactive operator action, not a batch job."""

_HISTORY_LOCK_TIMEOUT_SECONDS = 2.0
"""Shorter still: a dashboard poll must never queue behind a slow writer."""


class PolicyMutationKind(StrEnum):
    """The four edits a repository-scoped operator may make."""

    CREATE = "create"
    UPDATE = "update"
    DISABLE = "disable"
    ROLLBACK = "rollback"


class MutationOutcome(StrEnum):
    """Whether a recorded intent reached the snapshot."""

    COMMITTED = "committed"
    ABORTED = "aborted"


class JournalOutcome(StrEnum):
    """What recovery found and did."""

    NONE = "none"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled-back"
    UNREADABLE = "unreadable"


class MutationRejection(StrEnum):
    """Why a mutation was refused, as a code an editor can render."""

    STALE_REVISION = "stale-revision"
    SNAPSHOT_CORRUPT = "snapshot-corrupt"
    AUDIT_CHAIN_BROKEN = "audit-chain-broken"
    JOURNAL_UNREADABLE = "journal-unreadable"
    POLICY_NOT_FOUND = "policy-not-found"
    POLICY_ALREADY_EXISTS = "policy-already-exists"
    OUT_OF_SCOPE = "out-of-scope"
    UNKNOWN_REVISION = "unknown-revision"
    MALFORMED_MUTATION = "malformed-mutation"
    CREDENTIAL_SHAPED_VALUE = "credential-shaped-value"
    VALIDATION_FAILED = "validation-failed"


class PolicyMutation(BaseModel):
    """One requested edit, carrying the revision the editor loaded.

    There is deliberately **no actor field**: provenance comes from the
    authenticated boundary (``src/operator_identity.py``), never from a body a
    caller controls. ``extra="forbid"`` is what stops one being added by a
    client that hopes it will be believed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PolicyMutationKind
    expected_revision: int = Field(ge=0)
    policy: RoutingPolicy | None = None
    policy_id: str | None = Field(default=None, max_length=64)
    target_revision: int | None = Field(default=None, ge=0)


class MutationIntent(BaseModel):
    """The write-ahead record of a transaction that is about to be attempted.

    Identity fields (``mutation_id`` through ``recorded_at``) decide which branch
    recovery takes; the descriptive fields below them only enrich the audit
    record, so they carry defaults and a journal written by an older build stays
    recoverable rather than becoming an unreadable wedge.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation_id: str = Field(min_length=1, max_length=64)
    kind: PolicyMutationKind
    repo: str = Field(min_length=1, max_length=256)
    actor: str = Field(min_length=1, max_length=64)
    prior_revision: int = Field(ge=0)
    next_revision: int = Field(ge=0)
    next_content_hash: str = Field(min_length=1, max_length=128)
    recorded_at: str = Field(min_length=1, max_length=64)
    policy_ids: tuple[str, ...] = ()
    prior_content_hash: str = Field(default="", max_length=128)
    target_revision: int | None = None
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyDiff:
    """Which policy ids an edit adds, removes, or rewrites."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, list[str]]:
        """The shape carried on an audit payload."""
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    """What one repository's policy workspace currently holds.

    ``state`` is carried beside the contents for the same reason ADR-0139 kept it
    off the snapshot: ``absent`` (nobody has written a policy) and ``corrupt``
    (the file cannot be trusted) are different facts and an operator acts on them
    differently.
    """

    repo: str
    state: SnapshotState
    revision: int
    content_hash: str
    policies: tuple[RoutingPolicy, ...] = ()
    editable_policy_ids: tuple[str, ...] = ()
    issues: tuple[PolicyValidationIssue, ...] = ()

    @property
    def snapshot(self) -> PolicySnapshot:
        """The snapshot a resolver would be handed for this view."""
        return PolicySnapshot(
            revision=self.revision,
            policies=self.policies,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True, slots=True)
class PolicyPreview:
    """A candidate edit resolved against one pinned revision, with nothing written.

    ``rejection`` is a *reported* refusal rather than a raised one: a builder
    validates continuously, and an exception per keystroke is not that. The same
    refusal raised from :meth:`PolicyWorkspace.apply` is what stops the write.
    """

    before: PolicySnapshot
    after: PolicySnapshot
    diff: PolicyDiff
    issues: tuple[PolicyValidationIssue, ...] = ()
    stale: bool = False
    rejection: MutationRejection | None = None
    snapshot_state: SnapshotState = SnapshotState.OK

    @property
    def writable(self) -> bool:
        """Whether saving this exact edit now would be accepted."""
        return not self.stale and self.rejection is None and not self.issues


@dataclass(frozen=True, slots=True)
class MutationResult:
    """The revision a committed mutation produced."""

    revision: int
    prior_revision: int
    content_hash: str
    policies: tuple[RoutingPolicy, ...]
    diff: PolicyDiff
    audit_seq: int


@dataclass(frozen=True, slots=True)
class PolicyHistory:
    """The append-only mutation history plus whether it still verifies."""

    records: tuple[AuditRecord, ...]
    verification: ChainVerification
    truncated: bool = False


class PolicyMutationRejected(RuntimeError):
    """A mutation was refused; the previous revision is untouched."""

    def __init__(
        self,
        code: MutationRejection,
        detail: str = "",
        *,
        issues: Sequence[PolicyValidationIssue] = (),
        actual_revision: int | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.issues = tuple(issues)
        self.actual_revision = actual_revision
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


def is_editable_by(policy: RoutingPolicy, repo: str) -> bool:
    """Whether a repository-scoped operator owns this policy.

    Exactly one repository id and nothing that widens the rule past it. A class
    dimension, a system-safety flag, or a second repository makes the rule host
    business, and a repo editor renders it read-only rather than rewriting it.
    """
    return (
        tuple(policy.match.repo_ids) == (repo,)
        and not policy.match.repo_classes
        and not policy.system_safety
    )


class PolicyWorkspace:
    """The revision-safe write plane over one repository's policy snapshot."""

    def __init__(self, routing_dir: Path, *, repo: str) -> None:
        canonical = canonicalize_repo(repo)
        if canonical is None:
            raise ValueError(
                f"a policy workspace needs a canonical owner/repo, not {repo!r}; "
                "a lossy runtime slug can never satisfy repo_ids (ADR-0139 D2)"
            )
        self._repo = canonical
        self._dir = Path(routing_dir)
        self._store = RoutingPolicyStore(self._dir / POLICY_SNAPSHOT_FILENAME)
        self._audit = RoutingAuditLog(self._dir / POLICY_AUDIT_FILENAME)
        self._journal = self._dir / POLICY_JOURNAL_FILENAME
        self._lock_path = self._dir / POLICY_MUTATION_LOCK_FILENAME

    @property
    def repo(self) -> str:
        """The canonical repository this workspace edits."""
        return self._repo

    @property
    def store(self) -> RoutingPolicyStore:
        """The durable snapshot store (ADR-0139 D5)."""
        return self._store

    @property
    def audit(self) -> RoutingAuditLog:
        """The append-only mutation chain, which is also the revision history."""
        return self._audit

    # -- reading -----------------------------------------------------------

    def read(self) -> WorkspaceView:
        """Return the current snapshot and which of its policies are editable.

        Deliberately does **not** verify the audit chain: verification walks a
        growing file and this is the view a dashboard polls. Chain health belongs
        to :meth:`history`, which an operator opens deliberately.
        """
        load = self._store.load()
        snapshot = load.snapshot
        return WorkspaceView(
            repo=self._repo,
            state=load.state,
            revision=snapshot.revision,
            content_hash=snapshot.content_hash,
            policies=snapshot.policies,
            editable_policy_ids=tuple(
                policy.id
                for policy in snapshot.policies
                if is_editable_by(policy, self._repo)
            ),
            issues=validate_policies(snapshot.policies),
        )

    def history(self, *, limit: int = DEFAULT_HISTORY_LIMIT) -> PolicyHistory:
        """Return the most recent mutation records, newest last, plus verification.

        Read under the writer's own advisory lock. ``append_jsonl`` writes
        through a buffered writer, so a record larger than that buffer reaches
        disk in several ``write`` calls — and a reader that caught the gap would
        see a torn tail line and report a BROKEN CHAIN on the one panel whose
        entire job is trustworthiness. The lock is short-timeout and falls back
        to an unlocked read: worst case is exactly today's behaviour, never a
        hung poll.

        Blocking (a lock plus a full-file read). Async callers hand it to a
        thread, like :meth:`apply`.
        """
        bounded = max(1, min(limit, MAX_HISTORY_LIMIT))
        try:
            with file_lock(self._lock_path, timeout=_HISTORY_LOCK_TIMEOUT_SECONDS):
                return self._history_unlocked(bounded)
        except OSError:
            return self._history_unlocked(bounded)

    def _history_unlocked(self, bounded: int) -> PolicyHistory:
        verification = self._audit.verify()
        try:
            records = self._audit.read_all()
        except AuditChainError:
            # An unparseable line already failed verification above; returning
            # nothing beats returning a prefix that reads as the whole history.
            return PolicyHistory(records=(), verification=verification)
        return PolicyHistory(
            records=records[-bounded:],
            verification=verification,
            truncated=len(records) > bounded,
        )

    # -- previewing --------------------------------------------------------

    def preview(self, mutation: PolicyMutation) -> PolicyPreview:
        """Resolve a candidate edit against the current revision without writing."""
        load = self._store.load()
        before = load.snapshot
        if load.state is SnapshotState.CORRUPT:
            return PolicyPreview(
                before=before,
                after=before,
                diff=PolicyDiff(),
                rejection=MutationRejection.SNAPSHOT_CORRUPT,
                snapshot_state=load.state,
            )
        stale = before.revision != mutation.expected_revision
        try:
            policies = self._next_policies(mutation, before)
        except PolicyMutationRejected as rejected:
            return PolicyPreview(
                before=before,
                after=before,
                diff=PolicyDiff(),
                issues=rejected.issues,
                stale=stale,
                rejection=rejected.code,
                snapshot_state=load.state,
            )
        after = PolicySnapshot(
            revision=before.revision + 1,
            policies=policies,
            content_hash=hash_policies(policies),
        )
        return PolicyPreview(
            before=before,
            after=after,
            diff=_diff(before.policies, policies),
            issues=validate_policies(policies),
            stale=stale,
            snapshot_state=load.state,
        )

    # -- writing -----------------------------------------------------------

    def apply(
        self, mutation: PolicyMutation, *, actor: str, now: datetime
    ) -> MutationResult:
        """Commit one edit, or refuse it and leave the previous revision alone.

        Blocking by construction (an advisory file lock and two fsync'd writes).
        Async callers must hand it to a worker thread rather than run it on the
        event loop.
        """
        with file_lock(self._lock_path, timeout=_MUTATION_LOCK_TIMEOUT_SECONDS):
            return self._apply_locked(mutation, actor=actor, now=now)

    def _apply_locked(
        self, mutation: PolicyMutation, *, actor: str, now: datetime
    ) -> MutationResult:
        recovery = self._recover_locked(now=now)
        if recovery is JournalOutcome.UNREADABLE:
            raise PolicyMutationRejected(
                MutationRejection.JOURNAL_UNREADABLE,
                "an interrupted policy transaction could not be read; repair "
                f"or remove {self._journal} before writing again",
            )
        load = self._store.load()
        if load.state is SnapshotState.CORRUPT:
            raise PolicyMutationRejected(
                MutationRejection.SNAPSHOT_CORRUPT,
                "the policy snapshot on disk cannot be read; writing over it "
                "would restart the revision counter (ADR-0139 D5)",
            )
        verification = self._audit.verify()
        if not verification.ok:
            raise PolicyMutationRejected(
                MutationRejection.AUDIT_CHAIN_BROKEN,
                f"the mutation chain does not verify at seq {verification.broken_at_seq}",
            )
        before = load.snapshot
        if before.revision != mutation.expected_revision:
            raise PolicyMutationRejected(
                MutationRejection.STALE_REVISION,
                f"expected revision {mutation.expected_revision}, "
                f"but revision {before.revision} is current",
                actual_revision=before.revision,
            )
        policies = self._next_policies(mutation, before)
        issues = validate_policies(policies)
        if issues:
            raise PolicyMutationRejected(
                MutationRejection.VALIDATION_FAILED,
                "the resulting policy set is not admissible",
                issues=issues,
            )
        return self._commit(
            mutation, before=before, policies=policies, actor=actor, now=now
        )

    def _commit(
        self,
        mutation: PolicyMutation,
        *,
        before: PolicySnapshot,
        policies: tuple[RoutingPolicy, ...],
        actor: str,
        now: datetime,
    ) -> MutationResult:
        diff = _diff(before.policies, policies)
        intent = MutationIntent(
            mutation_id=_mutation_id(
                repo=self._repo,
                actor=actor,
                prior_revision=before.revision,
                next_content_hash=hash_policies(policies),
                recorded_at=now.isoformat(),
            ),
            kind=mutation.kind,
            repo=self._repo,
            actor=actor,
            prior_revision=before.revision,
            next_revision=before.revision + 1,
            next_content_hash=hash_policies(policies),
            recorded_at=now.isoformat(),
            policy_ids=tuple(policy.id for policy in policies),
            prior_content_hash=before.content_hash,
            target_revision=mutation.target_revision,
            added=diff.added,
            removed=diff.removed,
            changed=diff.changed,
        )
        # Write-ahead: the intent lands before the snapshot it describes, so a
        # crash anywhere after this point is recoverable rather than ambiguous.
        atomic_write(self._journal, json.dumps(intent.model_dump(mode="json")))
        snapshot = self._store.save(policies)
        record = self._audit.append(
            _committed_payload(intent, snapshot, recovered=False),
            recorded_at=intent.recorded_at,
        )
        # Only now is the transaction closed. An append that raised leaves the
        # journal in place, and the next recovery finishes it.
        self._journal.unlink(missing_ok=True)
        return MutationResult(
            revision=snapshot.revision,
            prior_revision=before.revision,
            content_hash=snapshot.content_hash,
            policies=snapshot.policies,
            diff=diff,
            audit_seq=record.seq,
        )

    # -- recovery ----------------------------------------------------------

    def recover(self, *, now: datetime) -> JournalOutcome:
        """Close any transaction an earlier process left open."""
        with file_lock(self._lock_path, timeout=_MUTATION_LOCK_TIMEOUT_SECONDS):
            return self._recover_locked(now=now)

    def _recover_locked(self, *, now: datetime) -> JournalOutcome:
        intent = self._read_journal()
        if intent is None:
            return (
                JournalOutcome.UNREADABLE
                if self._journal.exists()
                else JournalOutcome.NONE
            )
        load = self._store.load()
        landed = (
            load.state is SnapshotState.OK
            and load.snapshot.revision == intent.next_revision
            and load.snapshot.content_hash == intent.next_content_hash
        )
        # ONE idempotency check, above both branches: a crash between the append
        # and the unlink is possible on either path, and guarding only the
        # committed one would let recovery write a second `aborted` record for a
        # single intent. `mutation_id` identifies the transaction, not its
        # outcome, so it covers both payload kinds.
        head = self._audit.head()
        recorded = (
            head is not None and head.payload.get("mutation_id") == intent.mutation_id
        )
        if landed:
            if not recorded:
                self._audit.append(
                    _committed_payload(intent, load.snapshot, recovered=True),
                    recorded_at=intent.recorded_at,
                )
            self._journal.unlink(missing_ok=True)
            return JournalOutcome.COMPLETED
        # The atomic replace never happened, so the prior revision is still
        # authoritative and always was — recovery records that, it does not
        # invent the revision the interrupted write was reaching for.
        if not recorded:
            self._audit.append(
                _aborted_payload(intent, load), recorded_at=now.isoformat()
            )
        self._journal.unlink(missing_ok=True)
        return JournalOutcome.ROLLED_BACK

    def _read_journal(self) -> MutationIntent | None:
        try:
            raw = self._journal.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            return MutationIntent.model_validate(json.loads(raw))
        except (ValueError, TypeError):
            return None

    # -- the candidate policy set ------------------------------------------

    def _next_policies(
        self, mutation: PolicyMutation, before: PolicySnapshot
    ) -> tuple[RoutingPolicy, ...]:
        """Return the policy set this mutation would produce, or refuse it."""
        if mutation.kind is PolicyMutationKind.ROLLBACK:
            return self._rolled_back_policies(mutation, before)
        policy_id = self._target_id(mutation)
        existing = {candidate.id for candidate in before.policies}
        if mutation.kind is PolicyMutationKind.CREATE and policy_id in existing:
            raise PolicyMutationRejected(
                MutationRejection.POLICY_ALREADY_EXISTS, policy_id
            )
        if mutation.kind is not PolicyMutationKind.CREATE:
            self._require_editable_existing(policy_id, before)
        replacement = (
            _find(before.policies, policy_id).model_copy(update={"enabled": False})
            if mutation.kind is PolicyMutationKind.DISABLE
            else _body(mutation)
        )
        if not is_editable_by(replacement, self._repo):
            raise PolicyMutationRejected(
                MutationRejection.OUT_OF_SCOPE,
                f"{policy_id} is not a policy scoped to exactly {self._repo}",
            )
        return _refusing_credential_shaped(
            _sorted_policies(
                [
                    candidate
                    for candidate in before.policies
                    if candidate.id != policy_id
                ]
                + [replacement]
            ),
            baseline=before.policies,
        )

    def _target_id(self, mutation: PolicyMutation) -> str:
        """Return the policy id this mutation names, whichever end it carries it on."""
        if mutation.kind is not PolicyMutationKind.DISABLE:
            return _body(mutation).id
        if not mutation.policy_id:
            raise PolicyMutationRejected(
                MutationRejection.MALFORMED_MUTATION,
                "a disable names the policy id it disables",
            )
        return mutation.policy_id

    def _require_editable_existing(
        self, policy_id: str, before: PolicySnapshot
    ) -> None:
        current = next(
            (candidate for candidate in before.policies if candidate.id == policy_id),
            None,
        )
        if current is None:
            raise PolicyMutationRejected(MutationRejection.POLICY_NOT_FOUND, policy_id)
        if not is_editable_by(current, self._repo):
            raise PolicyMutationRejected(
                MutationRejection.OUT_OF_SCOPE,
                f"{policy_id} is inherited by {self._repo}, not owned by it",
            )

    def _rolled_back_policies(
        self, mutation: PolicyMutation, before: PolicySnapshot
    ) -> tuple[RoutingPolicy, ...]:
        """Return this repository's policies as of *target_revision*, scoped.

        Inherited policies are carried forward untouched: a repository-scoped
        rollback that restored a whole prior snapshot would silently revert a
        class or global rule this editor is not permitted to write.
        """
        if mutation.target_revision is None:
            raise PolicyMutationRejected(
                MutationRejection.MALFORMED_MUTATION,
                "a rollback names the revision it restores",
            )
        restored = self._policies_at(mutation.target_revision)
        inherited = [
            policy
            for policy in before.policies
            if not is_editable_by(policy, self._repo)
        ]
        owned = [policy for policy in restored if is_editable_by(policy, self._repo)]
        return _refusing_credential_shaped(
            _sorted_policies(inherited + owned), baseline=before.policies
        )

    def _policies_at(self, revision: int) -> tuple[RoutingPolicy, ...]:
        """Read a revision's policy set back out of the mutation chain.

        Revision 0 is the state before any policy was written and has no record;
        every later revision was recorded by the transaction that produced it.
        """
        if revision == 0:
            return ()
        try:
            records = self._audit.read_all()
        except AuditChainError as exc:  # pragma: no cover - verify() ran first
            raise PolicyMutationRejected(
                MutationRejection.AUDIT_CHAIN_BROKEN, str(exc)
            ) from exc
        for record in reversed(records):
            payload = record.payload
            if (
                payload.get("outcome") == MutationOutcome.COMMITTED.value
                and payload.get("new_revision") == revision
            ):
                return _parse_policies(payload.get("policies", []))
        raise PolicyMutationRejected(
            MutationRejection.UNKNOWN_REVISION,
            f"revision {revision} is not in this repository's mutation history",
        )


def _committed_payload(
    intent: MutationIntent, snapshot: PolicySnapshot, *, recovered: bool
) -> dict[str, Any]:
    """The one audit shape, built identically on the normal and recovery paths."""
    return {
        "record_kind": MUTATION_RECORD_KIND,
        "mutation_id": intent.mutation_id,
        "kind": intent.kind.value,
        "outcome": MutationOutcome.COMMITTED.value,
        "repo": intent.repo,
        "actor": intent.actor,
        "recovered": recovered,
        "prior_revision": intent.prior_revision,
        "new_revision": snapshot.revision,
        "prior_content_hash": intent.prior_content_hash,
        "new_content_hash": snapshot.content_hash,
        "target_revision": intent.target_revision,
        "diff": PolicyDiff(
            added=intent.added, removed=intent.removed, changed=intent.changed
        ).to_json_dict(),
        "policies": [policy.model_dump(mode="json") for policy in snapshot.policies],
    }


def _aborted_payload(intent: MutationIntent, load: SnapshotLoad) -> dict[str, Any]:
    """An intent that never reached the snapshot, recorded rather than forgotten.

    ``new_revision`` is the revision that REMAINS authoritative. A corrupt load
    reports revision 0, which is not that — so the intent's own
    ``prior_revision`` is used instead of publishing a zero the chain would then
    carry as fact.
    """
    snapshot = load.snapshot
    remaining = (
        snapshot.revision if load.state is SnapshotState.OK else intent.prior_revision
    )
    return {
        "record_kind": MUTATION_RECORD_KIND,
        "mutation_id": intent.mutation_id,
        "kind": intent.kind.value,
        "outcome": MutationOutcome.ABORTED.value,
        "repo": intent.repo,
        "actor": intent.actor,
        "recovered": True,
        "prior_revision": intent.prior_revision,
        "new_revision": remaining,
        "prior_content_hash": intent.prior_content_hash,
        "new_content_hash": snapshot.content_hash,
        "snapshot_state": load.state.value,
        "target_revision": intent.target_revision,
        "diff": PolicyDiff().to_json_dict(),
        "policies": [],
    }


def _mutation_id(
    *,
    repo: str,
    actor: str,
    prior_revision: int,
    next_content_hash: str,
    recorded_at: str,
) -> str:
    """Content-addressed transaction id — reproducible, and never a credential.

    Derived from what the transaction *is*, so recovery can recognise its own
    append after a crash without a random id it would have had to persist first.
    """
    material = f"{repo}|{actor}|{prior_revision}|{next_content_hash}|{recorded_at}"
    return "mut_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _refusing_credential_shaped(
    policies: tuple[RoutingPolicy, ...], *, baseline: Sequence[RoutingPolicy]
) -> tuple[RoutingPolicy, ...]:
    """Refuse a policy body carrying a credential-shaped value, and say only that.

    The snapshot is written by :func:`file_util.atomic_write`, which — unlike the
    audit chain's ``append_jsonl`` — does **not** redact on the way to disk, and
    the snapshot is served back over an unauthenticated read route. A credential
    pasted into a model id or an account id would therefore land durably and be
    echoed. Only *newly introduced* policies are scanned: a pre-existing bad row
    must not wedge every later edit, since repairing it is itself an edit.

    The refusal names the policy and the pattern label, never the matched text —
    an error message that quoted the credential back would be the leak.
    """
    existing = {_canonical_policy(policy) for policy in baseline}
    for policy in policies:
        blob = _canonical_policy(policy)
        if blob in existing:
            continue
        labels = scan_for_secrets(blob)
        if labels:
            raise PolicyMutationRejected(
                MutationRejection.CREDENTIAL_SHAPED_VALUE,
                f"{policy.id} carries a credential-shaped value ({labels[0]}); "
                "a policy never holds a secret (ADR-0138 D4)",
            )
    return policies


def _canonical_policy(policy: RoutingPolicy) -> str:
    return json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def _sorted_policies(policies: Sequence[RoutingPolicy]) -> tuple[RoutingPolicy, ...]:
    """Store policies in id order so a snapshot's bytes depend on its contents only."""
    return tuple(sorted(policies, key=lambda policy: policy.id))


def _find(policies: Sequence[RoutingPolicy], policy_id: str) -> RoutingPolicy:
    return next(policy for policy in policies if policy.id == policy_id)


def _body(mutation: PolicyMutation) -> RoutingPolicy:
    """The policy body a create or update must carry, or a typed refusal."""
    if mutation.policy is None:
        raise PolicyMutationRejected(
            MutationRejection.MALFORMED_MUTATION,
            f"a {mutation.kind.value} carries the policy body it writes",
        )
    return mutation.policy


def _parse_policies(raw: Any) -> tuple[RoutingPolicy, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(RoutingPolicy.model_validate(entry) for entry in raw)


def _diff(
    before: Sequence[RoutingPolicy], after: Sequence[RoutingPolicy]
) -> PolicyDiff:
    """Which ids an edit adds, removes, or rewrites."""
    prior = {policy.id: policy for policy in before}
    following = {policy.id: policy for policy in after}
    return PolicyDiff(
        added=tuple(sorted(set(following) - set(prior))),
        removed=tuple(sorted(set(prior) - set(following))),
        changed=tuple(
            sorted(
                policy_id
                for policy_id in set(prior) & set(following)
                if prior[policy_id] != following[policy_id]
            )
        ),
    )

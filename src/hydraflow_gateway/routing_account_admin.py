"""The audited administrative overlay: enable, drain, disable, revoke.

An account's *definition* is a restart-required deployment fact. Its
administrative *state* is the opposite: an operator has to be able to drain a
misbehaving account right now, and undo it a minute later, without a deploy.
This is the store that holds that, and it has one structural decision behind it.

**The hash-linked audit chain IS the state.** There is no separate snapshot file
to fall out of step with the log that describes it: :meth:`AccountAdminStore.read`
folds the chain, and ``revision`` is the chain's own length. One mutation is one
append, so there is no window in which a state change exists without its audit
record or an audit record exists without its state change — the failure mode a
two-file write would have needed a write-ahead journal to close. Mutations are
rare (a handful over a deployment's life), and an O(1) tail read of the chain
head lets an unchanged chain be served from cache, so folding is not a per-poll
cost.

Two behaviours follow from that and are worth stating rather than inferring:

* **Concurrency is optimistic on the chain's own revision.** A mutation declares
  the revision it was composed against and is refused with ``stale-revision`` if
  the chain has moved, so an old browser tab cannot silently undo an emergency
  disable. The refusal is total: nothing is appended, so a rejected mutation
  leaves no trace of having half-happened.
* **The chain is anchored, so truncating it is not a rollback.** A hash chain
  verified from the genesis hash forward is intact after its last N records are
  deleted — the shorter chain links perfectly. That is tolerable for a log and
  not tolerable for a *state*: dropping the trailing record would re-enable the
  account an operator disabled, and report the overlay as verified while doing
  it. Each commit therefore also writes a tiny anchor (record count and head
  hash). A chain shorter than its anchor, or one whose head disagrees with it,
  is :attr:`SnapshotState.CORRUPT`. The anchor is **not** a second copy of the
  state — it holds no account and no administrative value, only a monotonicity
  witness — so the single-writer property above is untouched, and the crash
  window runs the safe way: the anchor is written *after* the append, so a crash
  leaves the chain one record *ahead* of its anchor, which is accepted and
  re-anchored by the next commit.
* **A broken chain fails closed, and closed means *hold*.** ADR-0139 made a
  corrupt policy snapshot produce a held decision rather than a route, and the
  same reasoning applies with more force here: if the record of "which accounts
  did an operator withdraw?" cannot be trusted, treating every account as
  enabled would resurrect the account they disabled. :attr:`SnapshotState` rides
  on the view so the caller holds rather than guessing in either direction.

**On actor provenance, honestly.** The gateway's authenticated boundary is a
shared control token with no caller identity — the design's distinct read / mint
/ policy-admin scopes are not built yet. The recorded ``actor`` is therefore
supplied by the caller that already holds that token (HydraFlow's dashboard,
which authenticates a real operator before it proxies), and the record says so
in ``actor_authenticated_by`` rather than presenting a caller-declared string as
an authenticated identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from file_util import atomic_write, file_lock
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.routing_audit import (
    AuditChainError,
    AuditRecord,
    RoutingAuditLog,
)
from hydraflow_gateway.routing_policy import SnapshotState

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from hydraflow_gateway.routing_accounts import AccountRegistry

ACCOUNT_ADMIN_AUDIT_FILENAME = "account-admin-audit.jsonl"
ACCOUNT_ADMIN_HEAD_FILENAME = "account-admin-head.json"
ACCOUNT_ADMIN_LOCK_FILENAME = "account-admin.lock"
ACCOUNT_ADMIN_RECORD_KIND = "account-admin"

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500

_MUTATION_LOCK_TIMEOUT_SECONDS = 10.0
_AUTHENTICATED_BY = "gateway-control-token"


class AdminMutationKind(StrEnum):
    """What one administrative mutation did."""

    SET_STATE = "set-state"
    REVOKE_LEASES = "revoke-leases"


class AdminRejection(StrEnum):
    """Why an administrative mutation was refused, as a code rather than prose."""

    STALE_REVISION = "stale-revision"
    UNKNOWN_ACCOUNT = "unknown-account"
    AUDIT_CHAIN_BROKEN = "audit-chain-broken"


class AccountAdminRejected(RuntimeError):
    """An administrative mutation was refused before anything was written."""

    def __init__(
        self,
        rejection: AdminRejection,
        detail: str = "",
        *,
        actual_revision: int | None = None,
    ) -> None:
        super().__init__(detail or rejection.value)
        self.rejection = rejection
        self.detail = detail
        self.actual_revision = actual_revision


@dataclass(frozen=True, slots=True)
class AccountStateView:
    """The administrative overlay as it stands, plus how trustworthy it is."""

    state: SnapshotState
    revision: int
    states: Mapping[str, AdministrativeState]

    def administrative(self, account_id: str) -> AdministrativeState:
        """The state this account is in. Unmentioned accounts are enabled."""
        return self.states.get(account_id.strip().lower(), AdministrativeState.ENABLED)


@dataclass(frozen=True, slots=True)
class AdminMutationResult:
    """What one committed mutation produced."""

    revision: int
    record: AuditRecord
    view: AccountStateView


class AccountAdminStore:
    """The audited, revision-safe administrative overlay for one gateway."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._audit = RoutingAuditLog(directory / ACCOUNT_ADMIN_AUDIT_FILENAME)
        self._head_path = directory / ACCOUNT_ADMIN_HEAD_FILENAME
        self._lock_path = directory / ACCOUNT_ADMIN_LOCK_FILENAME
        self._cached_head: str | None = None
        self._cached_view: AccountStateView | None = None

    @property
    def audit(self) -> RoutingAuditLog:
        """The hash-linked chain that both records and defines the overlay."""
        return self._audit

    def read(self) -> AccountStateView:
        """Fold the chain into the current overlay. Never raises.

        An unreadable chain returns :attr:`SnapshotState.CORRUPT` with an empty
        overlay rather than an exception, because this is called on the live mint
        path: the caller holds the attempt, and an exception thrown there is a
        routing incident rather than an answer.
        """
        try:
            head = self._audit.head()
        except AuditChainError:
            return _corrupt()
        if head is None:
            return AccountStateView(state=SnapshotState.ABSENT, revision=0, states={})
        if self._cached_head == head.record_hash and self._cached_view is not None:
            return self._cached_view
        try:
            records = self._trusted_records(head)
        except AuditChainError:
            return _corrupt()
        if records is None:
            return _corrupt()
        view = AccountStateView(
            state=SnapshotState.OK,
            revision=head.seq + 1,
            states=_fold(records),
        )
        self._cached_head = head.record_hash
        self._cached_view = view
        return view

    def set_state(
        self,
        account_id: str,
        state: AdministrativeState,
        *,
        expected_revision: int,
        actor: str,
        recorded_at: str,
        registry: AccountRegistry,
    ) -> AdminMutationResult:
        """Move one account to *state*, or refuse without writing anything."""
        return self._commit(
            kind=AdminMutationKind.SET_STATE,
            account_id=account_id,
            expected_revision=expected_revision,
            actor=actor,
            recorded_at=recorded_at,
            registry=registry,
            extra=lambda: {"administrative_state": state.value},
        )

    def record_revocation(
        self,
        account_id: str,
        *,
        expected_revision: int,
        actor: str,
        recorded_at: str,
        registry: AccountRegistry,
        revoke: Callable[[], Sequence[str]],
    ) -> AdminMutationResult:
        """Revoke this account's leases and audit exactly what was revoked.

        *revoke* is called **inside** the mutation, after the revision check and
        before the append. That ordering is the decision: revoking first would
        let a stale request destroy leases and then be told 409, and appending
        first would record a revocation that had not happened yet. Doing it here
        means a refused request revokes nothing and a committed one records the
        ids it actually ended.

        A revoke is a blast-radius action rather than a state, and it is audited
        beside the state changes deliberately: "who took this account's leases
        away, and how many?" and "who disabled it?" are the same operator
        question asked twice, and splitting them across two logs is how the
        second half of an incident goes missing.
        """
        return self._commit(
            kind=AdminMutationKind.REVOKE_LEASES,
            account_id=account_id,
            expected_revision=expected_revision,
            actor=actor,
            recorded_at=recorded_at,
            registry=registry,
            extra=lambda: _revocation_payload(revoke()),
        )

    def history(self, *, limit: int = DEFAULT_HISTORY_LIMIT) -> tuple[AuditRecord, ...]:
        """The most recent mutations, newest first, bounded by *limit*."""
        bounded = max(1, min(limit, MAX_HISTORY_LIMIT))
        try:
            records = self._audit.read_all()
        except AuditChainError:
            return ()
        return tuple(reversed(records))[:bounded]

    # -- internals ----------------------------------------------------------

    def _trusted_records(self, head: AuditRecord) -> tuple[AuditRecord, ...] | None:
        """The chain's records, or ``None`` when it may not be trusted.

        Both checks run on every *re-fold*, not merely before a mutation. A
        reader that trusted the chain it was about to fold would publish exactly
        the overlay an attacker edited into it — and this overlay's whole job is
        to say which accounts an operator withdrew. The cache is what keeps that
        from being an O(chain) cost per poll: an unchanged head is served without
        re-reading, and the head itself is a bounded tail read.
        """
        if not self._audit.verify().ok or not self._anchored(head):
            return None
        return self._audit.read_all()

    def _anchored(self, head: AuditRecord) -> bool:
        """Whether the chain is at least as long as the anchor it last wrote.

        A chain with records but no anchor is refused outright: this store has
        written an anchor on every commit since it existed, so the only way to
        reach that state is for one of the two files to have been removed.
        """
        anchor = self._read_anchor()
        if anchor is None:
            return False
        records, head_hash = anchor
        if head.seq + 1 < records:
            return False
        return head.seq + 1 != records or head.record_hash == head_hash

    def _read_anchor(self) -> tuple[int, str] | None:
        try:
            raw = json.loads(self._head_path.read_text(encoding="utf-8"))
            return int(raw["records"]), str(raw["head_hash"])
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _write_anchor(self, record: AuditRecord) -> None:
        atomic_write(
            self._head_path,
            json.dumps(
                {"records": record.seq + 1, "head_hash": record.record_hash},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def _commit(
        self,
        *,
        kind: AdminMutationKind,
        account_id: str,
        expected_revision: int,
        actor: str,
        recorded_at: str,
        registry: AccountRegistry,
        extra: Callable[[], dict[str, Any]],
    ) -> AdminMutationResult:
        target = account_id.strip().lower()
        if registry.get(target) is None:
            raise AccountAdminRejected(
                AdminRejection.UNKNOWN_ACCOUNT,
                "no account with that id is registered",
            )
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with file_lock(self._lock_path, timeout=_MUTATION_LOCK_TIMEOUT_SECONDS):
            # Verified inside the lock and before the revision check: an
            # unverifiable chain must refuse EVERY mutation, or the first write
            # after tampering would extend a chain nobody can trust and make the
            # damage permanent.
            current = self.read()
            if current.state is SnapshotState.CORRUPT:
                # The store's own verdict, which covers BOTH a chain whose links
                # do not hold and one that was truncated back to a shorter valid
                # prefix. Checked before the revision so a rolled-back chain is
                # reported as the integrity failure it is rather than as a stale
                # revision the caller could "fix" by re-reading — and checked at
                # all because a write onto an untrustworthy chain would extend it
                # and make the damage permanent.
                raise AccountAdminRejected(
                    AdminRejection.AUDIT_CHAIN_BROKEN,
                    "the account administration chain does not verify",
                )
            if current.revision != expected_revision:
                raise AccountAdminRejected(
                    AdminRejection.STALE_REVISION,
                    f"expected revision {expected_revision}, but revision "
                    f"{current.revision} is current",
                    actual_revision=current.revision,
                )
            # Called here, inside the lock and after the revision check, so a
            # mutation with a side effect performs it only when it will commit.
            effect = extra()
            payload: dict[str, Any] = {
                "kind": ACCOUNT_ADMIN_RECORD_KIND,
                "mutation": kind.value,
                "account_id": target,
                "prior_revision": current.revision,
                "next_revision": current.revision + 1,
                "actor": actor,
                "actor_authenticated_by": _AUTHENTICATED_BY,
                **effect,
            }
            record = self._audit.append(payload, recorded_at=recorded_at)
            # After the append, deliberately. A crash between the two leaves the
            # chain one record AHEAD of its anchor, which reads as intact and is
            # re-anchored by the next commit; the reverse order would leave an
            # anchor ahead of the chain, which is indistinguishable from the
            # truncation the anchor exists to catch.
            self._write_anchor(record)
        # Outside the lock: the cache is invalidated by the head hash, so the
        # worst a concurrent reader sees is one extra fold.
        self._cached_head = None
        view = self.read()
        return AdminMutationResult(revision=view.revision, record=record, view=view)


class AccountStateRequest(BaseModel):
    """Body for ``PATCH /control/v2/accounts/{id}/state``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    administrative_state: AdministrativeState
    expected_revision: int = Field(ge=0)
    actor: str = Field(default="unattributed", min_length=1, max_length=256)
    """Who HydraFlow's authenticated boundary says asked. See the module note."""


class RevokeLeasesRequest(BaseModel):
    """Body for ``POST /control/v2/accounts/{id}/revoke-leases``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(ge=0)
    actor: str = Field(default="unattributed", min_length=1, max_length=256)


class AccountStateResponse(BaseModel):
    """The overlay after one committed state change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str
    administrative_state: AdministrativeState
    revision: int = Field(ge=0)


class RevokeLeasesResponse(BaseModel):
    """What one explicit blast-radius revocation actually ended."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str
    revoked_key_ids: tuple[str, ...]
    revision: int = Field(ge=0)


class AccountAdminEntry(BaseModel):
    """One audited administrative mutation, sanitized for an operator view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int = Field(ge=0)
    recorded_at: str
    mutation: str
    account_id: str
    actor: str
    actor_authenticated_by: str
    prior_revision: int = Field(ge=0)
    next_revision: int = Field(ge=0)
    administrative_state: str | None = None
    revoked_key_count: int | None = Field(default=None, ge=0)


class AccountAdminAuditView(BaseModel):
    """The read model behind ``GET /control/v2/accounts/audit``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    revision: int = Field(ge=0)
    chain_verified: bool
    entries: tuple[AccountAdminEntry, ...] = ()


def audit_view(store: AccountAdminStore, *, limit: int) -> AccountAdminAuditView:
    """Project the chain into the operator's history. Never raises.

    ``chain_verified`` is published rather than assumed, and a chain that does
    not verify returns **no entries**: rendering records from a log whose links
    are broken would present tampered history as history.
    """
    view = store.read()
    if view.state is SnapshotState.CORRUPT:
        # The store's own verdict, not `verify()` alone: a chain truncated back
        # to a shorter valid prefix verifies, and publishing `chain_verified`
        # from that would tell an operator the record is intact while showing
        # them the overlay someone rolled back.
        return AccountAdminAuditView(
            revision=view.revision, chain_verified=False, entries=()
        )
    entries = tuple(
        _entry(record) for record in store.history(limit=limit) if _is_admin(record)
    )
    return AccountAdminAuditView(
        revision=view.revision, chain_verified=True, entries=entries
    )


def _is_admin(record: AuditRecord) -> bool:
    return record.payload.get("kind") == ACCOUNT_ADMIN_RECORD_KIND


def _entry(record: AuditRecord) -> AccountAdminEntry:
    payload = record.payload
    revoked = payload.get("revoked_key_count")
    return AccountAdminEntry(
        seq=record.seq,
        recorded_at=record.recorded_at,
        mutation=str(payload.get("mutation", "")),
        account_id=str(payload.get("account_id", "")),
        actor=str(payload.get("actor", "")),
        actor_authenticated_by=str(payload.get("actor_authenticated_by", "")),
        prior_revision=int(payload.get("prior_revision", 0)),
        next_revision=int(payload.get("next_revision", 0)),
        administrative_state=(
            None
            if payload.get("administrative_state") is None
            else str(payload["administrative_state"])
        ),
        revoked_key_count=None if revoked is None else int(revoked),
    )


def _revocation_payload(revoked_key_ids: Sequence[str]) -> dict[str, Any]:
    """The audited shape of one revocation.

    Key ids are the ledger's non-secret correlation column (ADR-0138 §D4): a
    ULID whose entropy lives in the separate secret half of the token. Naming
    them is what makes a revocation reconcilable against the requests it ended.
    """
    return {
        "revoked_key_count": len(revoked_key_ids),
        "revoked_key_ids": sorted(revoked_key_ids),
    }


def _corrupt() -> AccountStateView:
    return AccountStateView(state=SnapshotState.CORRUPT, revision=0, states={})


def _fold(records: Sequence[AuditRecord]) -> dict[str, AdministrativeState]:
    """Replay the chain into the overlay it describes. Unknown records are ignored."""
    states: dict[str, AdministrativeState] = {}
    for record in records:
        payload = record.payload
        if payload.get("mutation") != AdminMutationKind.SET_STATE.value:
            continue
        account_id = str(payload.get("account_id", "")).strip().lower()
        raw = str(payload.get("administrative_state", ""))
        try:
            states[account_id] = AdministrativeState(raw)
        except ValueError:
            # A state this build does not know is read as DISABLED rather than
            # crashing the fold or falling back to enabled. Every value this enum
            # has ever held is a *withdrawal* of some strength, so an unknown one
            # is far more likely to be a narrower withdrawal from a newer build
            # than a permission — and resurrecting an account an operator took
            # out is the one outcome this overlay exists to prevent. A downgrade
            # therefore over-withdraws, loudly and reversibly, instead of
            # silently re-enabling.
            states[account_id] = AdministrativeState.DISABLED
    return states

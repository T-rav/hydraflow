"""Enable, drain, disable and revoke: revision-safe, audited, and fail-closed.

The overlay's whole claim is that an operator's emergency disable cannot be
silently undone and cannot be lost. Three properties carry it: a stale revision
refuses without writing, the audit chain and the state are the same artefact so
neither can exist without the other, and a chain that does not verify refuses
every mutation and reports the overlay as untrustworthy rather than as empty.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.routing_account_admin import (
    ACCOUNT_ADMIN_AUDIT_FILENAME,
    ACCOUNT_ADMIN_HEAD_FILENAME,
    AccountAdminRejected,
    AccountAdminStore,
    AdminMutationKind,
    AdminRejection,
    _fold,
    audit_view,
)
from hydraflow_gateway.routing_accounts import build_account_registry
from hydraflow_gateway.routing_audit import AuditChainError
from hydraflow_gateway.routing_policy import SnapshotState

_ZAI = legacy_account_id(ProviderBinding.ZAI_HARNESS)
_ANTHROPIC = legacy_account_id(ProviderBinding.ANTHROPIC)
_REGISTRY = build_account_registry(upstreams={})
_ACTOR = "operator@example.test"
_AT = "2026-08-22T10:00:00+00:00"


def _store(tmp_path: Path) -> AccountAdminStore:
    return AccountAdminStore(tmp_path / "accounts")


def _disable(store: AccountAdminStore, *, revision: int = 0, account: str = _ZAI):
    return store.set_state(
        account,
        AdministrativeState.DISABLED,
        expected_revision=revision,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
    )


# -- the empty overlay -------------------------------------------------------


def test_a_gateway_that_never_mutated_reports_an_absent_overlay(
    tmp_path: Path,
) -> None:
    assert _store(tmp_path).read().state is SnapshotState.ABSENT


def test_an_account_nobody_mentioned_is_enabled(tmp_path: Path) -> None:
    assert _store(tmp_path).read().administrative(_ZAI) is AdministrativeState.ENABLED


def test_an_empty_overlay_is_revision_zero(tmp_path: Path) -> None:
    assert _store(tmp_path).read().revision == 0


# -- committing a state change ----------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(AdministrativeState.DRAINING, id="drain"),
        pytest.param(AdministrativeState.DISABLED, id="disable"),
        pytest.param(AdministrativeState.ENABLED, id="re-enable"),
    ],
)
def test_a_committed_state_change_is_what_the_overlay_reports(
    tmp_path: Path, state: AdministrativeState
) -> None:
    store = _store(tmp_path)
    store.set_state(
        _ZAI,
        state,
        expected_revision=0,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
    )
    assert store.read().administrative(_ZAI) is state


def test_a_committed_mutation_advances_the_revision(tmp_path: Path) -> None:
    assert _disable(_store(tmp_path)).revision == 1


def test_one_account_s_state_leaves_another_alone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    assert store.read().administrative(_ANTHROPIC) is AdministrativeState.ENABLED


def test_a_later_mutation_supersedes_an_earlier_one(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    store.set_state(
        _ZAI,
        AdministrativeState.ENABLED,
        expected_revision=1,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
    )
    assert store.read().administrative(_ZAI) is AdministrativeState.ENABLED


def test_a_mutated_overlay_reads_as_trustworthy(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    assert store.read().state is SnapshotState.OK


# -- the audit record --------------------------------------------------------


def test_the_mutation_is_recorded_with_the_action_it_took(tmp_path: Path) -> None:
    record = _disable(_store(tmp_path)).record
    assert record.payload["mutation"] == AdminMutationKind.SET_STATE.value


def test_the_mutation_records_the_revisions_it_moved_between(tmp_path: Path) -> None:
    payload = _disable(_store(tmp_path)).record.payload
    assert (payload["prior_revision"], payload["next_revision"]) == (0, 1)


def test_the_mutation_records_the_actor_that_asked_for_it(tmp_path: Path) -> None:
    assert _disable(_store(tmp_path)).record.payload["actor"] == _ACTOR


def test_the_mutation_says_what_actually_authenticated_it(tmp_path: Path) -> None:
    payload = _disable(_store(tmp_path)).record.payload
    assert payload["actor_authenticated_by"] == "gateway-control-token"


def test_the_chain_verifies_after_a_mutation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    assert store.audit.verify().ok is True


def test_history_reports_the_newest_mutation_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    store.set_state(
        _ANTHROPIC,
        AdministrativeState.DRAINING,
        expected_revision=1,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
    )
    assert store.history()[0].payload["account_id"] == _ANTHROPIC


def test_history_is_bounded_by_the_limit_it_is_given(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for revision in range(3):
        store.set_state(
            _ZAI,
            AdministrativeState.DRAINING,
            expected_revision=revision,
            actor=_ACTOR,
            recorded_at=_AT,
            registry=_REGISTRY,
        )
    assert len(store.history(limit=2)) == 2


# -- optimistic concurrency --------------------------------------------------


def test_a_stale_revision_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(store, revision=0)
    assert excinfo.value.rejection is AdminRejection.STALE_REVISION


def test_a_stale_refusal_reports_the_revision_that_is_current(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(store, revision=0)
    assert excinfo.value.actual_revision == 1


def test_a_stale_mutation_leaves_the_overlay_exactly_as_it_was(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _disable(store)
    with pytest.raises(AccountAdminRejected):
        store.set_state(
            _ZAI,
            AdministrativeState.ENABLED,
            expected_revision=0,
            actor=_ACTOR,
            recorded_at=_AT,
            registry=_REGISTRY,
        )
    assert store.read().administrative(_ZAI) is AdministrativeState.DISABLED


def test_a_stale_mutation_appends_nothing_to_the_chain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)
    with pytest.raises(AccountAdminRejected):
        _disable(store, revision=0)
    assert store.audit.verify().records == 1


def test_an_unknown_account_cannot_be_administered(tmp_path: Path) -> None:
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(_store(tmp_path), account="no-such-account")
    assert excinfo.value.rejection is AdminRejection.UNKNOWN_ACCOUNT


def test_an_unknown_account_leaves_no_chain_behind(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(AccountAdminRejected):
        _disable(store, account="no-such-account")
    assert store.read().revision == 0


# -- revocation is audited beside the state changes --------------------------


def test_a_revocation_is_recorded_as_its_own_kind(tmp_path: Path) -> None:
    result = _store(tmp_path).record_revocation(
        _ZAI,
        expected_revision=0,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
        revoke=lambda: ["key-a", "key-b"],
    )
    assert result.record.payload["mutation"] == AdminMutationKind.REVOKE_LEASES.value


def test_a_revocation_records_the_leases_it_ended(tmp_path: Path) -> None:
    result = _store(tmp_path).record_revocation(
        _ZAI,
        expected_revision=0,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
        revoke=lambda: ["key-b", "key-a"],
    )
    assert result.record.payload["revoked_key_ids"] == ["key-a", "key-b"]


def test_a_stale_revocation_revokes_nothing_at_all(tmp_path: Path) -> None:
    """The effect runs inside the mutation, so a refused one never performs it."""
    store = _store(tmp_path)
    _disable(store)
    performed: list[str] = []
    with pytest.raises(AccountAdminRejected):
        store.record_revocation(
            _ZAI,
            expected_revision=0,
            actor=_ACTOR,
            recorded_at=_AT,
            registry=_REGISTRY,
            revoke=lambda: performed.append("ran") or [],
        )
    assert performed == []


def test_a_revocation_leaves_the_administrative_state_alone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_revocation(
        _ZAI,
        expected_revision=0,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
        revoke=lambda: ["key-a"],
    )
    assert store.read().administrative(_ZAI) is AdministrativeState.ENABLED


# -- a chain that cannot be trusted fails closed -----------------------------


def _tamper(tmp_path: Path) -> AccountAdminStore:
    """Disable an account, edit the record, and hand back a FRESH reader.

    Fresh deliberately: an attacker edits a file, not a live object's cache, and
    the reader that has to catch it is the next process to open the chain.
    """
    _disable(_store(tmp_path))
    chain = tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME
    chain.write_text(
        chain.read_text(encoding="utf-8").replace("disabled", "enabled"),
        encoding="utf-8",
    )
    return _store(tmp_path)


def test_a_tampered_chain_reports_the_overlay_as_untrustworthy(
    tmp_path: Path,
) -> None:
    assert _tamper(tmp_path).read().state is SnapshotState.CORRUPT


def test_a_tampered_chain_refuses_every_further_mutation(tmp_path: Path) -> None:
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(_tamper(tmp_path), revision=1)
    assert excinfo.value.rejection is AdminRejection.AUDIT_CHAIN_BROKEN


def test_a_tampered_chain_never_reports_the_tampered_state(tmp_path: Path) -> None:
    assert _tamper(tmp_path).read().states == {}


def test_an_untampered_chain_is_read_by_a_fresh_process(tmp_path: Path) -> None:
    _disable(_store(tmp_path))
    assert _store(tmp_path).read().administrative(_ZAI) is AdministrativeState.DISABLED


# -- the head anchor: truncation is a rollback, not a shorter valid chain -----


def _truncate(tmp_path: Path, *, lines: int = 1) -> AccountAdminStore:
    """Disable two accounts, delete trailing records, and read afresh.

    A hash chain verified forward from genesis is *intact* after its tail is
    removed, which is exactly why the anchor exists.
    """
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    chain = tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME
    kept = chain.read_text(encoding="utf-8").splitlines()[:-lines]
    chain.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
    return _store(tmp_path)


def test_a_truncated_chain_still_verifies_as_a_chain(tmp_path: Path) -> None:
    """The premise: forward verification alone cannot see a missing tail."""
    assert _truncate(tmp_path).audit.verify().ok is True


def test_a_truncated_chain_is_nonetheless_reported_as_corrupt(tmp_path: Path) -> None:
    assert _truncate(tmp_path).read().state is SnapshotState.CORRUPT


def test_a_truncated_chain_never_resurrects_the_account_it_dropped(
    tmp_path: Path,
) -> None:
    """The whole point: dropping a record must not re-enable what it disabled."""
    assert _truncate(tmp_path).read().states == {}


def test_a_truncated_chain_refuses_every_further_mutation(tmp_path: Path) -> None:
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(_truncate(tmp_path), revision=1)
    assert excinfo.value.rejection is AdminRejection.AUDIT_CHAIN_BROKEN


def test_a_deleted_anchor_is_refused_rather_than_trusted(tmp_path: Path) -> None:
    """This store anchors on every commit, so a chain with none was tampered with."""
    store = _store(tmp_path)
    _disable(store)
    (tmp_path / "accounts" / ACCOUNT_ADMIN_HEAD_FILENAME).unlink()

    assert _store(tmp_path).read().state is SnapshotState.CORRUPT


def test_a_chain_ahead_of_its_anchor_is_accepted(tmp_path: Path) -> None:
    """The crash window runs the safe way: the anchor is written after the append."""
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    anchor = tmp_path / "accounts" / ACCOUNT_ADMIN_HEAD_FILENAME
    stale = json.loads(anchor.read_text(encoding="utf-8"))
    stale["records"] = 1
    anchor.write_text(json.dumps(stale), encoding="utf-8")

    assert _store(tmp_path).read().state is SnapshotState.OK


def test_the_audit_view_reports_a_rolled_back_chain_as_unverified(
    tmp_path: Path,
) -> None:
    """Never tell an operator the record is intact while showing them a rollback."""
    assert audit_view(_truncate(tmp_path), limit=10).chain_verified is False


def test_the_audit_view_reports_an_intact_chain_as_verified(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _disable(store)

    assert audit_view(_store(tmp_path), limit=10).chain_verified is True


# -- an unknown administrative state is a withdrawal, not a permission -------


def test_an_unrecognised_administrative_state_is_read_as_disabled(
    tmp_path: Path,
) -> None:
    """A downgrade must over-withdraw, never resurrect what an operator took out."""
    store = _store(tmp_path)
    _disable(store)
    chain = tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME
    tampered = chain.read_text(encoding="utf-8").replace(
        '"disabled"', '"quarantined-in-a-newer-build"'
    )
    chain.write_text(tampered, encoding="utf-8")
    fresh = _store(tmp_path)
    # The edit breaks the hash chain, so read the fold directly rather than
    # through the (correctly) corrupt view.
    folded = _fold(fresh.audit.read_all())

    assert folded[_ZAI] is AdministrativeState.DISABLED


def test_a_reader_never_sees_an_overlay_that_disagrees_with_its_revision(
    tmp_path: Path,
) -> None:
    """The property the single-tuple cache exists for, asserted on the CONTENT.

    Four threads read while a writer alternates one account between draining and
    enabled. Every sampled overlay must match what the chain said at the revision
    the same read reported — a stale view served under a fresh head's name is a
    pair that disagrees, which is what two separate rebinds would allow.
    Asserting only on ``state`` cannot see it: the stale view is a valid ``OK``.
    """
    store = _store(tmp_path)
    samples: list[tuple[int, AdministrativeState]] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            view = store.read()
            if view.state is SnapshotState.OK:
                samples.append((view.revision, view.administrative(_ZAI)))

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        for revision in range(8):
            store.set_state(
                _ZAI,
                AdministrativeState.DRAINING
                if revision % 2 == 0
                else AdministrativeState.ENABLED,
                expected_revision=revision,
                actor=_ACTOR,
                recorded_at=_AT,
                registry=_REGISTRY,
            )
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    # Revision N was written by record N-1, whose state alternates on parity.
    def expected(revision: int) -> AdministrativeState:
        return (
            AdministrativeState.DRAINING
            if (revision - 1) % 2 == 0
            else AdministrativeState.ENABLED
        )

    assert all(state is expected(revision) for revision, state in samples)


def test_a_read_reports_the_overlay_its_own_revision_implies(tmp_path: Path) -> None:
    """Non-vacuity for the sweep above: it must sample a real, checkable pair."""
    store = _store(tmp_path)
    _disable(store)
    view = store.read()

    assert (view.revision, view.administrative(_ZAI)) == (
        1,
        AdministrativeState.DISABLED,
    )


def test_a_reader_never_sees_a_transient_corrupt_verdict(tmp_path: Path) -> None:
    """What the seeded anchor and the confirming re-read buy, together."""
    store = _store(tmp_path)
    seen: list[SnapshotState] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            seen.append(store.read().state)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        for revision in range(6):
            store.set_state(
                _ZAI,
                AdministrativeState.DRAINING,
                expected_revision=revision,
                actor=_ACTOR,
                recorded_at=_AT,
                registry=_REGISTRY,
            )
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    assert SnapshotState.CORRUPT not in seen


def test_a_genuinely_broken_chain_survives_the_confirming_re_read(
    tmp_path: Path,
) -> None:
    """One retry distinguishes a torn append from damage; it does not excuse it."""
    assert _truncate(tmp_path).read().state is SnapshotState.CORRUPT


def test_a_read_that_lands_mid_append_is_retried_rather_than_believed(
    tmp_path: Path,
) -> None:
    """Deterministic stand-in for the race the concurrency test only samples.

    A read that catches the chain mid-append sees a torn final line and raises;
    one look cannot tell that from damage, and two can.
    """
    store = _store(tmp_path)
    _disable(store)
    fresh = _store(tmp_path)
    intact = fresh.audit.head
    calls = {"n": 0}

    def torn_once():  # noqa: ANN202 - the store's own return type
        calls["n"] += 1
        if calls["n"] == 1:
            raise AuditChainError("unreadable audit record: torn append")
        return intact()

    fresh.audit.head = torn_once  # type: ignore[method-assign]

    assert fresh.read().administrative(_ZAI) is AdministrativeState.DISABLED


def test_the_retry_is_exactly_one(tmp_path: Path) -> None:
    """A chain that will not read twice holds the mint rather than spinning."""
    store = _store(tmp_path)
    _disable(store)
    fresh = _store(tmp_path)
    calls = {"n": 0}

    def always_torn():  # noqa: ANN202 - the store's own return type
        calls["n"] += 1
        raise AuditChainError("unreadable audit record")

    fresh.audit.head = always_torn  # type: ignore[method-assign]
    state = fresh.read().state

    assert (state, calls["n"]) == (SnapshotState.CORRUPT, 2)


def test_a_warm_cache_never_lets_a_mutation_land_on_a_broken_chain(
    tmp_path: Path,
) -> None:
    """The cache is keyed on the HEAD hash, so an earlier record can be edited.

    A reader that hit the cache would skip both the chain verification and the
    anchor check, and a *write* accepted on that basis extends the broken chain
    and makes the damage permanent. The mutation drops the cache inside the lock
    precisely so it decides from the file.
    """
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    store.set_state(
        _ZAI,
        AdministrativeState.DRAINING,
        expected_revision=2,
        actor=_ACTOR,
        recorded_at=_AT,
        registry=_REGISTRY,
    )
    store.read()  # warm the cache on the current head
    chain = tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME
    records = chain.read_text(encoding="utf-8").splitlines()
    records[0] = records[0].replace('"disabled"', '"enabled"')
    chain.write_text("".join(f"{line}\n" for line in records), encoding="utf-8")

    with pytest.raises(AccountAdminRejected) as excinfo:
        store.set_state(
            _ZAI,
            AdministrativeState.ENABLED,
            expected_revision=3,
            actor=_ACTOR,
            recorded_at=_AT,
            registry=_REGISTRY,
        )

    assert excinfo.value.rejection is AdminRejection.AUDIT_CHAIN_BROKEN


def test_a_warm_cache_never_lets_a_mutation_extend_a_broken_chain(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    store.read()
    chain = tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME
    records = chain.read_text(encoding="utf-8").splitlines()
    records[0] = records[0].replace('"disabled"', '"enabled"')
    chain.write_text("".join(f"{line}\n" for line in records), encoding="utf-8")
    with pytest.raises(AccountAdminRejected):
        _disable(store, revision=2)

    assert len(chain.read_text(encoding="utf-8").splitlines()) == 2


def _emptied(tmp_path: Path) -> AccountAdminStore:
    """Truncate the chain to nothing — the cheapest rollback there is."""
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    (tmp_path / "accounts" / ACCOUNT_ADMIN_AUDIT_FILENAME).write_text(
        "", encoding="utf-8"
    )
    return _store(tmp_path)


def test_a_chain_truncated_to_nothing_is_corrupt_rather_than_absent(
    tmp_path: Path,
) -> None:
    """Only CORRUPT holds the mint; ABSENT would wave every account through."""
    assert _emptied(tmp_path).read().state is SnapshotState.CORRUPT


def test_a_chain_truncated_to_nothing_never_re_enables_its_accounts(
    tmp_path: Path,
) -> None:
    assert _emptied(tmp_path).read().states == {}


def test_a_chain_truncated_to_nothing_refuses_every_mutation(
    tmp_path: Path,
) -> None:
    with pytest.raises(AccountAdminRejected) as excinfo:
        _disable(_emptied(tmp_path), revision=0)
    assert excinfo.value.rejection is AdminRejection.AUDIT_CHAIN_BROKEN


def test_a_chain_truncated_to_nothing_reports_itself_unverified(
    tmp_path: Path,
) -> None:
    assert audit_view(_emptied(tmp_path), limit=10).chain_verified is False


def test_a_gateway_that_never_mutated_is_still_plainly_absent(
    tmp_path: Path,
) -> None:
    """The contrast: no chain and no anchor is a fresh install, not a rollback."""
    assert _store(tmp_path).read().state is SnapshotState.ABSENT


def test_a_view_reports_the_revision_of_the_overlay_it_published(
    tmp_path: Path,
) -> None:
    """Both halves come from one read of the chain, so they cannot disagree.

    Taking the revision from the cheap tail read and the states from the full
    read lets a writer append between the two, publishing an overlay one record
    ahead of the revision it is labelled with — and an operator then composes an
    ``expected_revision`` against a number that never described what they saw.
    """
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    view = store.read()

    assert (view.revision, len(view.states)) == (2, 2)


def test_a_stale_tail_read_does_not_publish_a_revision_the_overlay_outran(
    tmp_path: Path,
) -> None:
    """Deterministic stand-in for a writer appending between the two reads.

    ``head()`` is a cheap bounded tail read and ``read_all()`` is a separate full
    read; a writer landing between them leaves the first behind the second. The
    view must be built entirely from the second, or it reports a revision that
    never described the overlay beside it.
    """
    store = _store(tmp_path)
    _disable(store)
    _disable(store, revision=1, account=_ANTHROPIC)
    fresh = _store(tmp_path)
    stale = fresh.audit.read_all()[0]
    fresh.audit.head = lambda: stale  # type: ignore[method-assign]
    view = fresh.read()

    assert (view.revision, len(view.states)) == (2, 2)

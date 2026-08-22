"""Enable, drain, disable and revoke: revision-safe, audited, and fail-closed.

The overlay's whole claim is that an operator's emergency disable cannot be
silently undone and cannot be lost. Three properties carry it: a stale revision
refuses without writing, the audit chain and the state are the same artefact so
neither can exist without the other, and a chain that does not verify refuses
every mutation and reports the overlay as untrustworthy rather than as empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.routing_account_admin import (
    ACCOUNT_ADMIN_AUDIT_FILENAME,
    AccountAdminRejected,
    AccountAdminStore,
    AdminMutationKind,
    AdminRejection,
)
from hydraflow_gateway.routing_accounts import build_account_registry
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

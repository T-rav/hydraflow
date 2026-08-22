"""Durable versioned policy snapshots: revisions, hashes, and failing closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.routing_policy import (
    PolicySnapshot,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    SnapshotState,
    hash_policies,
)
from hydraflow_gateway.routing_store import (
    PolicyValidationError,
    RoutingPolicyStore,
)


def _policy(policy_id: str = "project-x-zai", **overrides: object) -> RoutingPolicy:
    fields: dict[str, object] = {
        "id": policy_id,
        "priority": 100,
        "match": RoutingMatch(repo_ids=("acme/project-x",)),
        "action": RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
    }
    fields.update(overrides)
    return RoutingPolicy(**fields)  # type: ignore[arg-type]


def _store(tmp_path: Path) -> RoutingPolicyStore:
    return RoutingPolicyStore(tmp_path / "routing" / "policies.json")


def test_a_host_that_never_wrote_a_policy_reports_absent_not_corrupt(
    tmp_path: Path,
) -> None:
    """The ordinary state of every host, and it is not a fault."""
    assert _store(tmp_path).load().state is SnapshotState.ABSENT


def test_an_absent_snapshot_loads_as_revision_zero(tmp_path: Path) -> None:
    """Revision 0 is the identity every later revision counts up from."""
    assert _store(tmp_path).load().snapshot.revision == 0


def test_the_first_save_creates_revision_one(tmp_path: Path) -> None:
    """A revision is what makes a decision replayable later."""
    assert _store(tmp_path).save([_policy()]).revision == 1


def test_each_save_bumps_the_revision(tmp_path: Path) -> None:
    """Revisions are monotonic, so a decision citing one is unambiguous."""
    store = _store(tmp_path)
    store.save([_policy()])

    assert store.save([_policy()]).revision == 2


def test_a_saved_snapshot_reads_back_with_its_policies(tmp_path: Path) -> None:
    """Durability is the point of the file."""
    store = _store(tmp_path)
    store.save([_policy()])

    assert store.load().snapshot.policies == (_policy(),)


def test_a_saved_snapshot_reads_back_as_trustworthy(tmp_path: Path) -> None:
    """A round trip must not look like tampering."""
    store = _store(tmp_path)
    store.save([_policy()])

    assert store.load().state is SnapshotState.OK


def test_the_snapshot_carries_the_content_hash_of_its_own_policies(
    tmp_path: Path,
) -> None:
    """The hash, not the revision number, proves *which* policies were in force."""
    snapshot = _store(tmp_path).save([_policy()])

    assert snapshot.content_hash == hash_policies([_policy()])


def test_a_hand_edited_policy_file_loads_as_corrupt(tmp_path: Path) -> None:
    """The hash is what stands between an edited file and an unauthorised route."""
    store = _store(tmp_path)
    store.save([_policy()])
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["policies"][0]["priority"] = 9_000
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    assert store.load().state is SnapshotState.CORRUPT


def test_a_corrupt_file_yields_an_empty_snapshot_rather_than_partial_policies(
    tmp_path: Path,
) -> None:
    """Half a policy set is more dangerous than none; the resolver holds instead."""
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")

    assert store.load().snapshot == PolicySnapshot.empty()


def test_unparseable_json_loads_as_corrupt_not_absent(tmp_path: Path) -> None:
    """ "Unreadable" and "never written" must not collapse into one signal."""
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")

    assert store.load().state is SnapshotState.CORRUPT


def test_a_conflicting_policy_set_is_refused(tmp_path: Path) -> None:
    """The write never lands, so the resolver never has to guess."""
    conflicting = _policy(
        "other", action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC)
    )

    with pytest.raises(PolicyValidationError):
        _store(tmp_path).save([_policy(), conflicting])


def test_a_refused_write_leaves_no_file_behind(tmp_path: Path) -> None:
    """Validation happens before the atomic write, not after it."""
    store = _store(tmp_path)
    conflicting = _policy(
        "other", action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC)
    )

    with pytest.raises(PolicyValidationError):
        store.save([_policy(), conflicting])

    assert not store.path.exists()


def test_a_refused_write_names_every_issue_it_found(tmp_path: Path) -> None:
    """An operator fixing a rejected policy set needs the list, not the first item."""
    bad = _policy("BAD ID", match=RoutingMatch(repo_ids=("acme-project-x",)))

    with pytest.raises(PolicyValidationError) as caught:
        _store(tmp_path).save([bad])

    assert len(caught.value.issues) == 2


def test_a_refused_write_does_not_advance_the_revision(tmp_path: Path) -> None:
    """A rejected edit is not an edit."""
    store = _store(tmp_path)
    store.save([_policy()])
    conflicting = _policy(
        "other", action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC)
    )

    with pytest.raises(PolicyValidationError):
        store.save([_policy(), conflicting])

    assert store.load().snapshot.revision == 1


def test_saving_an_empty_policy_set_is_a_legitimate_revision(tmp_path: Path) -> None:
    """Withdrawing every policy is an auditable act, not a deletion."""
    store = _store(tmp_path)
    store.save([_policy()])

    assert store.save([]).revision == 2


def test_the_store_creates_its_parent_directory(tmp_path: Path) -> None:
    """A first write on a fresh host must not need a mkdir somewhere else."""
    store = _store(tmp_path)
    store.save([_policy()])

    assert store.path.parent.is_dir()

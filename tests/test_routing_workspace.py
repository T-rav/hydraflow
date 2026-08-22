"""Revision-safe policy mutation: the property is what a *failed* write leaves.

Every test here is about one invariant stated three ways (ADR-0140):

* a concurrent reader never observes a half-written revision;
* a refused edit leaves the previous revision byte-identical;
* a mutation and its audit append are one transaction, or neither.

The write path deliberately reuses ADR-0139's atomic write, order-independent
content hash, and hash-linked audit chain rather than growing a second
persistence path beside them.
"""

from __future__ import annotations

import contextlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from driver_contracts import WorkerRole
from hydraflow_gateway import routing_workspace
from hydraflow_gateway.models import ProviderBinding, RepoClass
from hydraflow_gateway.routing_policy import (
    PolicyValidationCode,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    SnapshotState,
    hash_policies,
)
from hydraflow_gateway.routing_store import POLICY_SNAPSHOT_FILENAME
from hydraflow_gateway.routing_workspace import (
    POLICY_JOURNAL_FILENAME,
    POLICY_MUTATION_LOCK_FILENAME,
    JournalOutcome,
    MutationRejection,
    PolicyMutation,
    PolicyMutationKind,
    PolicyMutationRejected,
    PolicyWorkspace,
)

_REPO = "acme/hydraflow"
_OTHER_REPO = "acme/other"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_ACTOR = "travis"


def _policy(
    policy_id: str = "pin-zai",
    *,
    repo: str = _REPO,
    enabled: bool = True,
    lock: ProviderBinding = ProviderBinding.ZAI_HARNESS,
    roles: tuple[WorkerRole, ...] = (),
    priority: int = 0,
) -> RoutingPolicy:
    return RoutingPolicy(
        id=policy_id,
        enabled=enabled,
        priority=priority,
        match=RoutingMatch(repo_ids=(repo,) if repo else (), roles=roles),
        action=RoutingAction(provider_lock=lock),
    )


def _workspace(tmp_path: Path) -> PolicyWorkspace:
    return PolicyWorkspace(tmp_path / "routing", repo=_REPO)


def _create(
    workspace: PolicyWorkspace,
    policy: RoutingPolicy,
    *,
    expected_revision: int = 0,
) -> int:
    result = workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=expected_revision,
            policy=policy,
        ),
        actor=_ACTOR,
        now=_NOW,
    )
    return result.revision


def _snapshot_bytes(tmp_path: Path) -> str:
    return (tmp_path / "routing" / POLICY_SNAPSHOT_FILENAME).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def test_a_host_that_never_wrote_a_policy_reads_as_absent(tmp_path: Path) -> None:
    """Absent is a normal state, not a degraded one (ADR-0139 D5)."""
    assert _workspace(tmp_path).read().state is SnapshotState.ABSENT


def test_an_unreadable_snapshot_reads_as_corrupt(tmp_path: Path) -> None:
    """Corrupt is never collapsed into "no policies" — that is a false coherence."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    (tmp_path / "routing" / POLICY_SNAPSHOT_FILENAME).write_text("{", encoding="utf-8")

    assert workspace.read().state is SnapshotState.CORRUPT


def test_an_inherited_policy_is_visible_but_not_editable(tmp_path: Path) -> None:
    """A repo view renders class/global rules; it may only edit its own."""
    workspace = _workspace(tmp_path)
    workspace.store.save((_policy("repo-rule"), _policy("class-rule", repo="")))

    view = workspace.read()

    assert view.editable_policy_ids == ("repo-rule",)


# --------------------------------------------------------------------------
# Create / update / disable
# --------------------------------------------------------------------------


def test_a_created_policy_lands_on_the_next_revision(tmp_path: Path) -> None:
    """The first write turns revision 0 into revision 1."""
    assert _create(_workspace(tmp_path), _policy()) == 1


def test_an_updated_policy_replaces_its_predecessor(tmp_path: Path) -> None:
    """An edit is a replacement at the same id, not a second row."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.UPDATE,
            expected_revision=1,
            policy=_policy(lock=ProviderBinding.ANTHROPIC),
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().policies == (_policy(lock=ProviderBinding.ANTHROPIC),)


def test_disabling_a_policy_keeps_it_in_the_snapshot(tmp_path: Path) -> None:
    """Soft disable over destructive delete: the rule stays, inert and visible."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.DISABLE,
            expected_revision=1,
            policy_id="pin-zai",
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().policies == (_policy(enabled=False),)


def test_every_mutation_creates_a_new_revision(tmp_path: Path) -> None:
    """Revisions only ever advance, so a decision's cited revision stays unique."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.DISABLE,
            expected_revision=1,
            policy_id="pin-zai",
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().revision == 2


# --------------------------------------------------------------------------
# Rejection — and what a rejection leaves behind
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=_policy(),
            ),
            MutationRejection.STALE_REVISION,
            id="a-write-against-the-revision-the-browser-loaded-an-edit-ago",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy(),
            ),
            MutationRejection.POLICY_ALREADY_EXISTS,
            id="a-create-that-would-shadow-an-existing-id",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.UPDATE,
                expected_revision=1,
                policy=_policy("absent-rule"),
            ),
            MutationRejection.POLICY_NOT_FOUND,
            id="an-update-of-a-policy-that-is-not-there",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.DISABLE,
                expected_revision=1,
                policy_id="absent-rule",
            ),
            MutationRejection.POLICY_NOT_FOUND,
            id="a-disable-of-a-policy-that-is-not-there",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("global-rule", repo=""),
            ),
            MutationRejection.OUT_OF_SCOPE,
            id="a-global-rule-written-through-a-repo-scoped-editor",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("foreign-rule", repo=_OTHER_REPO),
            ),
            MutationRejection.OUT_OF_SCOPE,
            id="a-rule-naming-somebody-elses-repository",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.ROLLBACK,
                expected_revision=1,
                target_revision=9,
            ),
            MutationRejection.UNKNOWN_REVISION,
            id="a-rollback-to-a-revision-that-never-existed",
        ),
    ],
)
def test_a_refused_mutation_names_its_reason(
    tmp_path: Path, mutation: PolicyMutation, expected: MutationRejection
) -> None:
    """Each refusal carries a code an editor can render, not one blanket error."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(mutation, actor=_ACTOR, now=_NOW)

    assert caught.value.code is expected


def test_a_stale_write_reports_the_revision_that_actually_won(
    tmp_path: Path,
) -> None:
    """A 409 an operator can act on names the revision to reload."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=_policy("second"),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.actual_revision == 1


def test_an_equal_precedence_conflict_is_refused_before_the_write(
    tmp_path: Path,
) -> None:
    """The store already refuses ties; the workspace surfaces them, not a tiebreak."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy("pin-zai", roles=(WorkerRole.IMPLEMENTER,)))

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy(
                    "pin-claude",
                    roles=(WorkerRole.IMPLEMENTER,),
                    lock=ProviderBinding.ANTHROPIC,
                ),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert [issue.code for issue in caught.value.issues] == [
        PolicyValidationCode.EQUAL_PRECEDENCE_CONFLICT
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=_policy("second"),
            ),
            id="a-stale-revision",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("global-rule", repo=""),
            ),
            id="an-out-of-scope-policy",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("pin-claude", lock=ProviderBinding.ANTHROPIC),
            ),
            id="an-equal-precedence-conflict",
        ),
        pytest.param(
            PolicyMutation(
                kind=PolicyMutationKind.UPDATE,
                expected_revision=1,
                policy=_policy("absent-rule"),
            ),
            id="an-update-of-a-missing-policy",
        ),
    ],
)
def test_a_refused_mutation_leaves_the_previous_revision_byte_identical(
    tmp_path: Path, mutation: PolicyMutation
) -> None:
    """The revision-safety property: a rejected edit is a no-op on disk."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    before = _snapshot_bytes(tmp_path)

    with pytest.raises(PolicyMutationRejected):
        workspace.apply(mutation, actor=_ACTOR, now=_NOW)

    assert _snapshot_bytes(tmp_path) == before


def test_a_refused_mutation_appends_nothing_to_the_audit_chain(
    tmp_path: Path,
) -> None:
    """An audit that recorded refusals would let a reader infer a revision gap."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    with pytest.raises(PolicyMutationRejected):
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=_policy("second"),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert len(workspace.history().records) == 1


def test_a_corrupt_snapshot_refuses_every_mutation(tmp_path: Path) -> None:
    """Writing over an unreadable snapshot would restart the revision counter."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    (tmp_path / "routing" / POLICY_SNAPSHOT_FILENAME).write_text("{", encoding="utf-8")

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("second"),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.code is MutationRejection.SNAPSHOT_CORRUPT


def test_a_broken_audit_chain_refuses_every_mutation(tmp_path: Path) -> None:
    """Rollback reads the chain, so an unverifiable chain cannot be built on."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    tampered = json.loads(workspace.audit.path.read_text(encoding="utf-8"))
    tampered["payload"]["actor"] = "somebody-else"
    workspace.audit.path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=1,
                policy=_policy("second"),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.code is MutationRejection.AUDIT_CHAIN_BROKEN


# --------------------------------------------------------------------------
# Rollback
# --------------------------------------------------------------------------


def test_a_rollback_creates_a_new_revision_rather_than_restoring_an_old_one(
    tmp_path: Path,
) -> None:
    """History is append-only: revision 3 *contains* revision 1, it is not it."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    _create(workspace, _policy("second"), expected_revision=1)

    result = workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.ROLLBACK,
            expected_revision=2,
            target_revision=1,
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert result.revision == 3


def test_a_rollback_restores_the_targeted_policy_set(tmp_path: Path) -> None:
    """The point of the new revision is that it holds the old contents."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    _create(workspace, _policy("second"), expected_revision=1)

    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.ROLLBACK,
            expected_revision=2,
            target_revision=1,
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().policies == (_policy(),)


def test_a_rollback_to_revision_zero_clears_this_repos_policies(
    tmp_path: Path,
) -> None:
    """Revision 0 is a real target: the state before any policy was written."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.ROLLBACK,
            expected_revision=1,
            target_revision=0,
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().policies == ()


def test_a_rollback_leaves_inherited_policies_alone(tmp_path: Path) -> None:
    """A repo-scoped rollback may not silently revert a rule it cannot edit."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.store.save((_policy(), _policy("class-rule", repo="")))

    workspace.apply(
        PolicyMutation(
            kind=PolicyMutationKind.ROLLBACK,
            expected_revision=2,
            target_revision=0,
        ),
        actor=_ACTOR,
        now=_NOW,
    )

    assert workspace.read().policies == (_policy("class-rule", repo=""),)


# --------------------------------------------------------------------------
# Atomicity: the snapshot replace and the audit append are one transaction
# --------------------------------------------------------------------------


def test_a_committed_mutation_records_exactly_one_audit_entry(
    tmp_path: Path,
) -> None:
    """One mutation, one hash-linked record — the denominator of an audit."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    assert len(workspace.history().records) == 1


def test_the_audit_entry_names_the_authenticated_actor(tmp_path: Path) -> None:
    """Provenance comes from the boundary, so it must reach the durable record."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    assert workspace.history().records[0].payload["actor"] == _ACTOR


def test_the_audit_entry_pins_both_sides_of_the_revision_move(
    tmp_path: Path,
) -> None:
    """ "From 0 to 1" is the fact a reader replays; either half alone is not."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    payload = workspace.history().records[0].payload

    assert (payload["prior_revision"], payload["new_revision"]) == (0, 1)


def test_the_audit_chain_verifies_after_a_mutation(tmp_path: Path) -> None:
    """A record that cannot be verified is a log, not evidence (ADR-0139 D6)."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    assert workspace.history().verification.ok is True


def test_an_interrupted_transaction_whose_snapshot_landed_is_completed(
    tmp_path: Path,
) -> None:
    """Recovery finishes the audit append the crash cut off, once."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.audit.path.unlink()
    _replay_journal_for_last_mutation(workspace, tmp_path)

    outcome = workspace.recover(now=_NOW)

    assert outcome is JournalOutcome.COMPLETED


def test_a_completed_recovery_restores_the_missing_audit_record(
    tmp_path: Path,
) -> None:
    """ "Completed" has to mean the record exists, not that recovery said so."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.audit.path.unlink()
    _replay_journal_for_last_mutation(workspace, tmp_path)

    workspace.recover(now=_NOW)

    assert len(workspace.history().records) == 1


def test_an_interrupted_transaction_whose_snapshot_never_landed_rolls_back(
    tmp_path: Path,
) -> None:
    """The prior revision stays authoritative; the intent is recorded as aborted."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    _write_journal(
        tmp_path,
        {
            "mutation_id": "dead-beef",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": 1,
            "next_revision": 2,
            "next_content_hash": "sha256:" + "f" * 64,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": ["never-landed"],
        },
    )

    assert workspace.recover(now=_NOW) is JournalOutcome.ROLLED_BACK


def test_an_aborted_transaction_leaves_the_prior_revision_authoritative(
    tmp_path: Path,
) -> None:
    """Recovery must never invent the revision the crash was reaching for."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    _write_journal(
        tmp_path,
        {
            "mutation_id": "dead-beef",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": 1,
            "next_revision": 2,
            "next_content_hash": "sha256:" + "f" * 64,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": ["never-landed"],
        },
    )

    workspace.recover(now=_NOW)

    assert workspace.read().revision == 1


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    """A second pass over a closed journal must not append a second record."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.audit.path.unlink()
    _replay_journal_for_last_mutation(workspace, tmp_path)
    workspace.recover(now=_NOW)

    workspace.recover(now=_NOW)

    assert len(workspace.history().records) == 1


def test_a_clean_workspace_has_nothing_to_recover(tmp_path: Path) -> None:
    """The recovery path is inert when no transaction was interrupted."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    assert workspace.recover(now=_NOW) is JournalOutcome.NONE


def test_a_new_mutation_closes_an_interrupted_one_first(tmp_path: Path) -> None:
    """A stale journal may not be carried past the next write."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    workspace.audit.path.unlink()
    _replay_journal_for_last_mutation(workspace, tmp_path)

    _create(workspace, _policy("second"), expected_revision=1)

    assert not (tmp_path / "routing" / POLICY_JOURNAL_FILENAME).exists()


def test_an_unwritable_audit_leaves_the_transaction_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An append that never happened must not be reported as a closed write."""
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        type(workspace.audit),
        "append",
        _raise_os_error,
    )

    with pytest.raises(OSError):
        _create(workspace, _policy())

    assert (tmp_path / "routing" / POLICY_JOURNAL_FILENAME).exists()


def test_a_snapshot_replace_that_fails_leaves_a_recoverable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write-ahead ordering: the intent is on disk before the snapshot it names."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    monkeypatch.setattr(type(workspace.store), "save", _raise_os_error)

    with pytest.raises(OSError):
        _create(workspace, _policy("second"), expected_revision=1)

    assert (tmp_path / "routing" / POLICY_JOURNAL_FILENAME).exists()


def test_recovery_of_a_snapshot_that_never_landed_keeps_the_prior_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end crash story: interrupted write, then a clean recovery."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    monkeypatch.setattr(type(workspace.store), "save", _raise_os_error)
    with pytest.raises(OSError):
        _create(workspace, _policy("second"), expected_revision=1)
    monkeypatch.undo()

    workspace.recover(now=_NOW)

    assert workspace.read().revision == 1


def _raise_os_error(*_args: object, **_kwargs: object) -> None:
    raise OSError("sink is unwritable")


# --------------------------------------------------------------------------
# Concurrency and hashing
# --------------------------------------------------------------------------


def test_a_concurrent_reader_never_observes_a_half_written_revision(
    tmp_path: Path,
) -> None:
    """Every read is either the previous coherent revision or the next one."""
    workspace = _workspace(tmp_path)
    observed: list[bool] = []
    stop = threading.Event()

    def write() -> None:
        for index in range(24):
            workspace.apply(
                PolicyMutation(
                    kind=PolicyMutationKind.CREATE,
                    expected_revision=index,
                    policy=_policy(f"rule-{index}"),
                ),
                actor=_ACTOR,
                now=_NOW,
            )
        stop.set()

    def read() -> None:
        while not stop.is_set():
            view = workspace.read()
            observed.append(
                view.state is not SnapshotState.CORRUPT
                and view.content_hash == hash_policies(view.policies)
            )

    writer = threading.Thread(target=write)
    reader = threading.Thread(target=read)
    writer.start()
    reader.start()
    writer.join()
    reader.join()

    # Both halves matter: every read was coherent, and reads actually happened —
    # an empty observation list would prove nothing at all.
    assert (all(observed), bool(observed)) == (True, True)


def test_the_content_hash_does_not_depend_on_insertion_order(
    tmp_path: Path,
) -> None:
    """Two operators reaching the same policy set reach the same hash."""
    first = PolicyWorkspace(tmp_path / "a", repo=_REPO)
    second = PolicyWorkspace(tmp_path / "b", repo=_REPO)
    _create(first, _policy("alpha"))
    _create(first, _policy("beta"), expected_revision=1)
    _create(second, _policy("beta"))
    _create(second, _policy("alpha"), expected_revision=1)

    assert first.read().content_hash == second.read().content_hash


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------


def test_a_preview_writes_nothing(tmp_path: Path) -> None:
    """The builder must be able to ask "what would happen" without it happening."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    workspace.preview(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=1,
            policy=_policy("second"),
        )
    )

    assert workspace.read().revision == 1


def test_a_preview_reports_the_revision_the_edit_would_land_on(
    tmp_path: Path,
) -> None:
    """The after-snapshot is the exact snapshot a save would write."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    preview = workspace.preview(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=1,
            policy=_policy("second"),
        )
    )

    assert preview.after.revision == 2


def test_a_preview_reports_a_conflict_instead_of_raising(tmp_path: Path) -> None:
    """A builder validates continuously; an exception per keystroke is not that."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy("pin-zai"))

    preview = workspace.preview(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=1,
            policy=_policy("pin-claude", lock=ProviderBinding.ANTHROPIC),
        )
    )

    assert [issue.code for issue in preview.issues] == [
        PolicyValidationCode.EQUAL_PRECEDENCE_CONFLICT
    ]


def test_a_preview_of_a_stale_edit_says_so_without_refusing_to_render(
    tmp_path: Path,
) -> None:
    """An operator whose tab went stale still deserves to see the diff."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    preview = workspace.preview(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=0,
            policy=_policy("second"),
        )
    )

    assert preview.stale is True


def test_a_preview_diff_names_what_the_edit_adds(tmp_path: Path) -> None:
    """The before/after matrix needs the changed set, not just two snapshots."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())

    preview = workspace.preview(
        PolicyMutation(
            kind=PolicyMutationKind.CREATE,
            expected_revision=1,
            policy=_policy("second"),
        )
    )

    assert preview.diff.added == ("second",)


def test_the_repo_class_of_a_workspace_is_not_a_policy_dimension_it_edits(
    tmp_path: Path,
) -> None:
    """A repo editor writing a repo_classes rule would escape its own scope."""
    workspace = _workspace(tmp_path)

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=RoutingPolicy(
                    id="class-rule",
                    match=RoutingMatch(
                        repo_ids=(_REPO,), repo_classes=(RepoClass.HYDRAFLOW,)
                    ),
                    action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
                ),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.code is MutationRejection.OUT_OF_SCOPE


def test_a_non_canonical_repository_cannot_own_a_workspace(tmp_path: Path) -> None:
    """A lossy slug can never satisfy repo_ids, so it may not scope an editor."""
    with pytest.raises(ValueError, match="canonical"):
        PolicyWorkspace(tmp_path / "routing", repo="acme-hydraflow")


# --------------------------------------------------------------------------
# Journal helpers
# --------------------------------------------------------------------------


def _write_journal(tmp_path: Path, intent: dict[str, object]) -> None:
    path = tmp_path / "routing" / POLICY_JOURNAL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(intent), encoding="utf-8")


def _replay_journal_for_last_mutation(
    workspace: PolicyWorkspace, tmp_path: Path
) -> None:
    """Re-open the transaction that just committed, as a crash would have left it."""
    view = workspace.read()
    _write_journal(
        tmp_path,
        {
            "mutation_id": "replayed",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": view.revision - 1,
            "next_revision": view.revision,
            "next_content_hash": view.content_hash,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": [policy.id for policy in view.policies],
        },
    )


# --------------------------------------------------------------------------
# Escalation, recovery idempotency, and the journal's own hash check
# --------------------------------------------------------------------------


def test_a_repo_editor_cannot_claim_system_safety(tmp_path: Path) -> None:
    """A system-safety rule outranks every exact-project route by design.

    ``priority`` is a field this editor already controls, and two policies at
    ``SYSTEM_SAFETY`` are ordered by it — so a repo-scoped operator who could
    set the flag could outrank a host-admin's own invariant for their repo's
    traffic. This clause is the only thing stopping that.
    """
    workspace = _workspace(tmp_path)

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=RoutingPolicy(
                    id="escalate",
                    priority=10_000,
                    system_safety=True,
                    match=RoutingMatch(repo_ids=(_REPO,)),
                    action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
                ),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.code is MutationRejection.OUT_OF_SCOPE


def test_a_system_safety_rule_is_inherited_not_editable(tmp_path: Path) -> None:
    """It renders in the list, and the editor may not rewrite it either."""
    workspace = _workspace(tmp_path)
    workspace.store.save(
        (
            RoutingPolicy(
                id="host-invariant",
                system_safety=True,
                match=RoutingMatch(repo_ids=(_REPO,)),
                action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
            ),
        )
    )

    assert workspace.read().editable_policy_ids == ()


def test_a_credential_pasted_into_a_policy_is_refused(tmp_path: Path) -> None:
    """The snapshot is written unredacted and served over an open read route."""
    workspace = _workspace(tmp_path)

    with pytest.raises(PolicyMutationRejected) as caught:
        workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=0,
                policy=RoutingPolicy(
                    id="leaky",
                    match=RoutingMatch(repo_ids=(_REPO,)),
                    action=RoutingAction(
                        provider_lock=ProviderBinding.ZAI_HARNESS,
                        allowed_patterns=("sk-ant-" + "a" * 44,),
                    ),
                ),
            ),
            actor=_ACTOR,
            now=_NOW,
        )

    assert caught.value.code is MutationRejection.CREDENTIAL_SHAPED_VALUE


def test_a_journal_whose_hash_disagrees_is_not_treated_as_landed(
    tmp_path: Path,
) -> None:
    """Matching the revision is not enough: the CONTENTS have to match too."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    _write_journal(
        tmp_path,
        {
            "mutation_id": "hash-mismatch",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": 0,
            "next_revision": 1,
            "next_content_hash": "sha256:" + "f" * 64,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": ["something-else"],
        },
    )

    assert workspace.recover(now=_NOW) is JournalOutcome.ROLLED_BACK


def test_recovery_does_not_record_one_aborted_intent_twice(tmp_path: Path) -> None:
    """A crash between the aborted append and the journal unlink is recoverable.

    The committed branch was already guarded; without the same guard on the
    aborted branch, one interrupted intent produces two `aborted` records.
    """
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    intent = {
        "mutation_id": "never-landed",
        "kind": "create",
        "repo": _REPO,
        "actor": _ACTOR,
        "prior_revision": 1,
        "next_revision": 2,
        "next_content_hash": "sha256:" + "f" * 64,
        "recorded_at": _NOW.isoformat(),
        "policy_ids": ["never-landed"],
    }
    _write_journal(tmp_path, intent)
    workspace.recover(now=_NOW)
    _write_journal(tmp_path, intent)

    workspace.recover(now=_NOW)

    assert [record.payload["outcome"] for record in workspace.history().records] == [
        "committed",
        "aborted",
    ]


def test_an_aborted_record_names_the_revision_that_remains_authoritative(
    tmp_path: Path,
) -> None:
    """A corrupt load reports revision 0, which is not the surviving revision."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    (tmp_path / "routing" / POLICY_SNAPSHOT_FILENAME).write_text("{", encoding="utf-8")
    _write_journal(
        tmp_path,
        {
            "mutation_id": "aborted-over-corrupt",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": 1,
            "next_revision": 2,
            "next_content_hash": "sha256:" + "f" * 64,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": ["never-landed"],
        },
    )

    workspace.recover(now=_NOW)

    assert workspace.history().records[-1].payload["new_revision"] == 1


def test_the_history_read_takes_the_writers_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``append_jsonl`` can tear a large record across writes; the lock is the fix.

    A reader that caught the gap would see a half line and report a BROKEN CHAIN
    on the one panel whose entire job is trustworthiness.
    """
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    taken: list[Path] = []
    real = routing_workspace.file_lock

    @contextlib.contextmanager
    def recording(path: Path, **kwargs: object):
        taken.append(path)
        with real(path, **kwargs):
            yield

    monkeypatch.setattr(routing_workspace, "file_lock", recording)

    workspace.history()

    assert taken == [tmp_path / "routing" / POLICY_MUTATION_LOCK_FILENAME]


def test_reading_a_history_that_does_not_exist_creates_nothing(
    tmp_path: Path,
) -> None:
    """A pure read must not leave a routing directory and a lock file behind."""
    _workspace(tmp_path).history()

    assert not (tmp_path / "routing").exists()


def test_an_aborted_record_does_not_suppress_a_later_committed_one(
    tmp_path: Path,
) -> None:
    """``mutation_id`` names the transaction, not what became of it.

    With an injected clock — which every test and scenario in this repo uses —
    a retry reuses the id. If an ``aborted`` head suppressed the ``committed``
    append, a revision would sit authoritative on disk with no record: not
    replayable, and permanently un-rollback-to-able.
    """
    workspace = _workspace(tmp_path)
    intent = {
        "mutation_id": "retried",
        "kind": "create",
        "repo": _REPO,
        "actor": _ACTOR,
        "prior_revision": 0,
        "next_revision": 1,
        "next_content_hash": "sha256:" + "f" * 64,
        "recorded_at": _NOW.isoformat(),
        "policy_ids": ["pin-zai"],
    }
    _write_journal(tmp_path, intent)
    workspace.recover(now=_NOW)
    workspace.store.save((_policy(),))
    _write_journal(
        tmp_path,
        {**intent, "next_content_hash": workspace.read().content_hash},
    )

    workspace.recover(now=_NOW)

    assert [record.payload["outcome"] for record in workspace.history().records] == [
        "aborted",
        "committed",
    ]


def test_an_aborted_record_never_pairs_a_revision_with_another_revisions_hash(
    tmp_path: Path,
) -> None:
    """A false pair on a tamper-evident chain is worse than no record at all."""
    workspace = _workspace(tmp_path)
    _create(workspace, _policy())
    landed = workspace.read().content_hash
    (tmp_path / "routing" / POLICY_SNAPSHOT_FILENAME).write_text("{", encoding="utf-8")
    _write_journal(
        tmp_path,
        {
            "mutation_id": "aborted-over-corrupt",
            "kind": "create",
            "repo": _REPO,
            "actor": _ACTOR,
            "prior_revision": 1,
            "prior_content_hash": landed,
            "next_revision": 2,
            "next_content_hash": "sha256:" + "f" * 64,
            "recorded_at": _NOW.isoformat(),
            "policy_ids": ["never-landed"],
        },
    )

    workspace.recover(now=_NOW)
    payload = workspace.history().records[-1].payload

    assert (payload["new_revision"], payload["new_content_hash"]) == (1, landed)

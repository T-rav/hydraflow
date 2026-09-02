"""Install a repository's generated baseline policies, reversibly (#11991 AC2).

`routing_baseline.baseline_policies` says WHICH policies a repository's dials
imply. This puts them in the store, and — the half the criterion is actually
about — makes getting back out a first-class operation rather than a restore
from backup.

**The down-path is not new machinery.** A migration is a sequence of ordinary
`create` mutations against the audited revision store, so undoing it is the
`rollback` that store already has: roll back to the revision the migration
started from and the pre-migration policy set is in force again, as a NEW
revision, with history intact. That is why `migrate_dials_to_policy` returns
`prior_revision` — it is the argument the operator needs, and
:func:`down_path_mutation` builds exactly that mutation so the reverse is a
call rather than a paragraph of instructions somebody has to follow correctly
under pressure.

Nothing here changes how a spawn routes. The resolver still reads the legacy
dials; these policies sit in the store waiting for the switch. Migrating and
rolling back on a live system is, today, a no-op you can rehearse — which is
the point of landing it before the switch rather than with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydraflow_gateway.routing_workspace import PolicyMutation, PolicyMutationKind
from routing_baseline import baseline_policies

if TYPE_CHECKING:
    from datetime import datetime

    from config import HydraFlowConfig
    from hydraflow_gateway.routing_policy import RoutingPolicy
    from hydraflow_gateway.routing_workspace import PolicyWorkspace


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """What a migration did, and the one number needed to undo it."""

    #: The revision in force before the migration ran. The rollback target.
    prior_revision: int
    #: The revision the last created policy produced. Equals ``prior_revision``
    #: when the repository had no moved dials and nothing was written.
    revision: int
    #: The policies installed, in the order they were created.
    installed: tuple[RoutingPolicy, ...]

    @property
    def changed(self) -> bool:
        """Whether anything was written. A no-op migration still needs no undo."""
        return self.revision != self.prior_revision


def migrate_dials_to_policy(
    config: HydraFlowConfig,
    workspace: PolicyWorkspace,
    *,
    actor: str,
    now: datetime,
) -> MigrationResult:
    """Install *config*'s generated baseline policies as new revisions.

    Each policy is its own `create`, because the store's unit of both audit and
    rollback is the revision: one bulk write would be one thing to undo, but it
    would also be one line in the history for what an operator reads as several
    decisions.

    A repository whose dials are all on their defaults generates nothing, so
    this writes nothing and reports ``changed == False``. That is not a special
    case — it falls out of the generator declining to re-state a default.
    """
    policies = baseline_policies(config)
    prior = workspace.read().revision
    revision = prior
    for policy in policies:
        result = workspace.apply(
            PolicyMutation(
                kind=PolicyMutationKind.CREATE,
                expected_revision=revision,
                policy=policy,
            ),
            actor=actor,
            now=now,
        )
        revision = result.revision
    return MigrationResult(prior_revision=prior, revision=revision, installed=policies)


def down_path_mutation(result: MigrationResult) -> PolicyMutation:
    """The single mutation that undoes *result*.

    Written as a function rather than documented as a procedure for the reason
    #11994 gives about rollback generally: the moment an operator needs this is
    the worst moment to be reconstructing which revision to name.
    """
    return PolicyMutation(
        kind=PolicyMutationKind.ROLLBACK,
        expected_revision=result.revision,
        target_revision=result.prior_revision,
    )

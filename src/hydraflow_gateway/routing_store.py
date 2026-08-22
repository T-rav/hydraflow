"""Durable, versioned routing-policy snapshots (ADR-0139).

One file holds one revision of the whole policy set plus its content hash. A
write is atomic (temp file + ``os.replace`` via :func:`file_util.atomic_write`),
validated *before* it lands, and bumps the revision — so a reader either sees
the previous coherent revision or the next one, never a half-written set.

**There is no HTTP write route in this phase.** :meth:`RoutingPolicyStore.save`
exists so the snapshot format, the revision counter, and the hash are durable
and tested now, ahead of the policy workspace (#11538) that will expose them.

Loading fails *closed*. A file that will not parse, or whose recorded hash does
not match its own contents, returns :attr:`SnapshotState.CORRUPT` with an empty
snapshot — and the resolver turns that into a ``held`` decision rather than
quietly routing as though no policy had ever been written. An *absent* file is
a different fact and says so: it is the normal state of a host that has never
written a policy, and it resolves normally.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from file_util import atomic_write
from hydraflow_gateway.routing_policy import (
    PolicySnapshot,
    PolicyValidationIssue,
    SnapshotState,
    hash_policies,
    validate_policies,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from hydraflow_gateway.routing_policy import RoutingPolicy

POLICY_SNAPSHOT_FILENAME = "policies.json"


class PolicyValidationError(ValueError):
    """A policy set was refused before it could reach a durable snapshot."""

    def __init__(self, issues: Sequence[PolicyValidationIssue]) -> None:
        self.issues = tuple(issues)
        summary = ", ".join(f"{issue.code.value}:{issue.policy_id}" for issue in issues)
        super().__init__(f"policy set rejected ({summary})")


@dataclass(frozen=True, slots=True)
class SnapshotLoad:
    """What a load found, and how much it can be trusted.

    ``state`` is carried beside the snapshot rather than folded into it because
    the durable file has no business recording its own trustworthiness — that is
    a property of *this* read, and the resolver needs it to fail closed.
    """

    state: SnapshotState
    snapshot: PolicySnapshot


class RoutingPolicyStore:
    """Read and write the one policy snapshot file for a host."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """The snapshot file this store owns."""
        return self._path

    def load(self) -> SnapshotLoad:
        """Return the current snapshot, or a typed absent/corrupt result."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SnapshotLoad(SnapshotState.ABSENT, PolicySnapshot.empty())
        except OSError:
            return SnapshotLoad(SnapshotState.CORRUPT, PolicySnapshot.empty())
        try:
            snapshot = PolicySnapshot.model_validate(json.loads(raw))
        except (ValueError, TypeError):
            return SnapshotLoad(SnapshotState.CORRUPT, PolicySnapshot.empty())
        if snapshot.content_hash != hash_policies(snapshot.policies):
            # The hash is the only thing standing between a hand-edited policy
            # file and an enforced route nobody authorised.
            return SnapshotLoad(SnapshotState.CORRUPT, PolicySnapshot.empty())
        return SnapshotLoad(SnapshotState.OK, snapshot)

    def save(self, policies: Sequence[RoutingPolicy]) -> PolicySnapshot:
        """Validate, then atomically write the next revision of the policy set.

        Raises :class:`PolicyValidationError` — the write never lands — when the
        set carries a duplicate id, a non-canonical repository id, a literal
        family mapped to a foreign model, or an equal-precedence conflict.
        """
        issues = validate_policies(policies)
        if issues:
            raise PolicyValidationError(issues)
        current = self.load()
        snapshot = PolicySnapshot(
            revision=current.snapshot.revision + 1,
            policies=tuple(policies),
            content_hash=hash_policies(policies),
        )
        atomic_write(
            self._path,
            json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True),
        )
        return snapshot

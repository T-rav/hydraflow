"""The runtime half of #11544's "zero governed direct-provider bypass".

``tests/architecture/test_governed_spawn_seam.py`` (#11987) proves no *code
path* execs an agent without passing the resolver first. That is a claim about
the source. This is the claim an operator actually needs: that no *execution*
reached a provider without a resolved route.

The two are not the same and neither implies the other. A governed code path
still produces an ungoverned request if the route resolves to nothing and the
spawn proceeds anyway, and a repository added to ``GATEWAY_GOVERNED_REPOS``
after a process started keeps serving its already-minted v1 keys.

**It counts; it does not sample.** A sampled gauge that reads zero is
consistent with a bypass it did not look at, which is the one thing this must
never say. Every row in the window is classified.

**A row is ungoverned when it carries no ``route_decision_id``.** That column
is null on every v1 row by construction -- ``ledger.py`` calls it "exactly how
a governed request is told apart from an ungoverned one after the fact" -- so
the gauge reads the fact the ledger already records rather than re-deriving
governance from settings at read time. Re-deriving would make the gauge agree
with itself instead of with what happened (ADR-0143 Ruling 4/5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

    from hydraflow_gateway.ledger import GatewayLedgerRow

GOVERNANCE_GAUGE_SCHEMA_VERSION = 1


class UngovernedSpawn(BaseModel):
    """One request that reached a provider for a governed repo with no route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    repo_slug: str
    upstream_provider: str
    principal_id: str
    #: Present when the key was minted but the route was not — a narrower and
    #: more actionable fault than "no gateway record at all".
    mint_decision_id: str | None = None


class GovernanceGauge(BaseModel):
    """How many spawns bypassed the route, out of how many were examined."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = GOVERNANCE_GAUGE_SCHEMA_VERSION
    examined: int = Field(default=0, ge=0)
    """Every row in the window, governed or not. A denominator of zero and a
    numerator of zero are different states and must not both render as "ok"."""
    governed: int = Field(default=0, ge=0)
    ungoverned: int = Field(default=0, ge=0)
    offenders: tuple[UngovernedSpawn, ...] = ()

    @property
    def clean(self) -> bool:
        """True only when a governed repository was actually observed.

        An empty window is not a pass. "Nothing bypassed" and "nothing ran"
        are the same number and opposite facts, and a gauge that reported the
        second as the first would go green exactly when the ledger stopped
        being written.
        """
        return self.governed > 0 and self.ungoverned == 0


def measure_governance(
    rows: Iterable[GatewayLedgerRow], *, governs: Callable[[str], bool]
) -> GovernanceGauge:
    """Classify every row against the repositories the deployment governs.

    *governs* is the live predicate — ``GatewaySettings.governs`` — passed in
    rather than a copied set, so the gauge asks the same question the mint
    boundary asks. A gauge holding its own copy of the governed set would keep
    reading zero after an operator changed it.
    """
    examined = 0
    governed = 0
    offenders: list[UngovernedSpawn] = []
    for row in rows:
        examined += 1
        if not governs(row.repo_slug):
            continue
        governed += 1
        if row.route_decision_id is not None:
            continue
        offenders.append(
            UngovernedSpawn(
                request_id=row.request_id,
                repo_slug=row.repo_slug,
                upstream_provider=str(row.upstream_provider),
                principal_id=row.principal.id,
                mint_decision_id=row.mint_decision_id,
            )
        )
    return GovernanceGauge(
        examined=examined,
        governed=governed,
        ungoverned=len(offenders),
        offenders=tuple(offenders),
    )

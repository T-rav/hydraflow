"""Recognise the factory's own chore/maintenance activity.

The factory opens a steady trickle of *self*-maintenance PRs that document
or regenerate its own artifacts rather than change the product:

- ``chore(wiki): maintenance``   — ``RepoWikiLoop``     (branch ``hydraflow/wiki-maint-*``)
- ``chore(arch): regenerate …``  — ``DiagramLoop``      (branch ``arch-regen-auto``)
- ``feat(ul): term-proposer …``  — ``term_proposer_loop`` (branch ``ul-proposer/*``)
- UL evidence/edges/pruner       — the other UL loops   (branch ``ul-*/``)
- ``chore(rc): promotion``       — ``StagingPromotionLoop`` (branch ``rc/*``)
- pricing refresh                — ``pricing_refresh_loop`` (branch ``pricing-refresh-auto``)

Promoting *these* into the repo wiki (via the reflection bridge / shipped-gap
ingest on merge) makes the wiki document the factory eating its own tail: a
self-maintenance merge generates an ``ingest-entry`` → the ``RepoWikiLoop``
opens *another* ``chore(wiki): maintenance`` PR → which merges → churn. The
wiki must track *meaningful external/feature change*, so the ingest paths use
:func:`is_factory_self_maintenance` to skip the factory's own chores.

The predicate is deliberately **narrow**: it matches only the exact
factory-owned branch prefixes and the four factory-internal conventional-commit
scopes (``chore(wiki)``, ``chore(arch)``, ``chore(rc)``, ``feat(ul)``) plus the
two loop-emitted maintenance labels. A genuine ``feat(...)`` / ``fix(...)`` /
``refactor(...)`` change — including a real ``chore(deps)`` bump — is *not*
matched, so its reflections still reach the wiki. Being conservative here is the
whole point: a false positive rots the wiki by dropping a real learning; a false
negative merely lets one self-chore slip through.

This module is intentionally dependency-free and pure so it is unit-testable in
isolation and safe to import from the merge / ingest paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Branch prefixes owned exclusively by the factory's maintenance loops. No human
# or normal-pipeline (``agent/issue-N``) branch uses these, so a prefix match is
# an unambiguous self-maintenance signal. ``rc/`` mirrors the default
# ``HydraFlowConfig.rc_branch_prefix``; RC promotion PRs target ``main`` and are
# merged by the promotion loop, but the prefix is included for completeness so
# any code path that does route one here treats it as self-maintenance.
_MAINTENANCE_BRANCH_PREFIXES: tuple[str, ...] = (
    "hydraflow/wiki-maint-",  # repo_wiki_loop
    "arch-regen-auto",  # diagram_loop (_REGEN_BRANCH)
    "ul-proposer/",  # term_proposer_loop
    "ul-evidence/",  # entry_evidence_loop
    "ul-edges/",  # edge_proposer_loop
    "ul-pruner/",  # term_pruner_loop
    "pricing-refresh-auto",  # pricing_refresh_loop (_REGEN_BRANCH)
    "rc/",  # staging_promotion_loop (default rc_branch_prefix)
)

# Conventional-commit scopes that name factory-internal artifacts. These catch a
# self-maintenance item that is processed through the *issue* pipeline (branch
# ``agent/issue-N``) — e.g. a ``chore(arch): unassigned functional area`` issue —
# where the branch prefix is generic but the title still names the artifact.
# Kept to the four factory-owned scopes; generic ``chore:`` / ``chore(deps):`` is
# NOT listed because those can be real, wiki-worthy work.
_MAINTENANCE_TITLE_PREFIXES: tuple[str, ...] = (
    "chore(wiki)",
    "chore(arch)",
    "chore(rc)",
    "feat(ul)",
)

# Labels the maintenance loops stamp on the issues they file for themselves.
_MAINTENANCE_LABELS: frozenset[str] = frozenset(
    {
        "arch-regen",  # diagram_loop coverage issues
        "pricing-refresh",  # pricing_refresh_loop
    }
)


def is_factory_self_maintenance(
    *,
    branch: str | None = None,
    title: str | None = None,
    labels: Iterable[str] = (),
) -> bool:
    """Return True when a PR/issue is the factory's own chore/maintenance work.

    Matches on any one of the three independent signals — the caller passes
    whatever it has at the emission point:

    - ``branch`` starts with a factory-owned maintenance branch prefix, or
    - ``title`` starts with a factory-internal conventional-commit scope
      (case-insensitive), or
    - ``labels`` contains a loop-emitted maintenance label.

    Pure and side-effect free. All arguments are optional so a caller with only
    a branch, only a title, or only labels can still get a useful answer.
    """
    if branch and branch.startswith(_MAINTENANCE_BRANCH_PREFIXES):
        return True
    if title and title.strip().lower().startswith(_MAINTENANCE_TITLE_PREFIXES):
        return True
    return any(label in _MAINTENANCE_LABELS for label in labels)

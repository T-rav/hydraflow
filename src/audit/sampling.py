"""Pure stratified random sampling for the re-audit (#10370).

``select_sample`` takes the merged changes of a tick, the governed base rate,
and an injected ``random.Random`` (seedable, so selection is deterministic
under test), and returns the subset to re-audit. Per-change inclusion
probability is ``min(1.0, base_rate * stratum_weight(class))`` — high-blast-
radius classes are elevated (``stratify``), sampling is Bernoulli per change so
the expected sample size tracks the rate without a fixed quota.

Sampling is the point; ``budget`` caps the SELECTED set so a synthetic backlog
never blows the per-tick token budget (exhaustive re-review is a non-goal).
"""

from __future__ import annotations

import random

from audit.models import MergedChange
from audit.stratify import classify_blast_radius, stratum_weight

# Conventional-commit subject prefixes that mark a merge as one of the FACTORY's
# OWN chore/maintenance artifacts — housekeeping the factory generated itself,
# NOT substantive product change. Re-auditing these is flux: the
# ``SampledAuditLoop`` was filing "re-audit disagreement" findings about the
# factory's own make-work (e.g. #10461 ``chore(wiki): maintenance``, #10439
# ``feat(ul): term-proposer``) during otherwise-idle windows.
#
# Each prefix maps 1:1 to a maintenance loop's FIXED branch + title, so the
# merged commit subject is a reliable discriminator even after a squash-merge
# has discarded the branch name (``MergedChange`` carries the subject, not the
# branch/author/labels):
#
#   chore(wiki):     repo_wiki_loop           branch hydraflow/wiki-maint-*
#   chore(arch):     diagram_loop / auto_pr   branch arch-regen-auto
#   chore(rc):       staging_promotion_loop   branch rc/*
#   chore(pricing):  pricing_refresh_loop     branch pricing-refresh-auto
#   feat(ul):        term_proposer / term_pruner / edge_proposer /
#                    entry_evidence           branch ul-*
#
# Substantive product work is DELIBERATELY absent: ``feat(``/``fix(`` on real
# scopes (including ``feat(wiki)`` / ``fix(wiki)`` product changes and
# ``chore(deps)`` bumps) still samples — re-reviewing REAL merged work is the
# audit's entire value. Keep this list legible: add a prefix HERE (not a magic
# string at a call site) when a new factory maintenance loop lands.
_SELF_CHORE_SUBJECT_PREFIXES: tuple[str, ...] = (
    "chore(wiki):",
    "chore(arch):",
    "chore(rc):",
    "chore(pricing):",
    "feat(ul):",
)


def is_self_chore_change(change: MergedChange) -> bool:
    """True when *change* is one of the factory's OWN chore/maintenance merges.

    Matched case-insensitively against the merged commit subject's
    conventional-commit prefix — see ``_SELF_CHORE_SUBJECT_PREFIXES`` for the
    per-loop mapping. Pure, so the exclusion is a unit assertion.

    A self-chore is excluded from the audit sample entirely by ``select_sample``
    (never classified, never Bernoulli-selected), so the adversarial re-audit
    stops filing disagreements about the factory's own make-work and only
    re-reviews substantive external change. The consuming loop's SHA cursor
    still advances unconditionally, so an excluded change is never re-examined
    on a later tick.
    """
    subject = change.subject.strip().lower()
    return any(subject.startswith(prefix) for prefix in _SELF_CHORE_SUBJECT_PREFIXES)


def inclusion_probability(change: MergedChange, base_rate: float) -> float:
    """Stratified per-change inclusion probability, capped at certainty."""
    weight = stratum_weight(classify_blast_radius(change))
    return min(1.0, max(0.0, base_rate) * weight)


def select_sample(
    changes: list[MergedChange],
    *,
    base_rate: float,
    rng: random.Random,
) -> list[MergedChange]:
    """Return the stratified Bernoulli sample of *changes* at *base_rate*.

    Order-preserving over *changes*. Deterministic for a seeded *rng* — the
    loop threads a per-tick seeded ``Random`` so a tick's selection is
    reproducible for the audit record and unit tests.
    """
    selected: list[MergedChange] = []
    for change in changes:
        # SELF/CHORE EXCLUSION — applied BEFORE classification + selection: a
        # factory-generated chore/maintenance merge (wiki maintenance, arch
        # regen, RC promotion, UL proposers) is skipped entirely so the
        # adversarial re-audit only ever re-reviews substantive external change.
        # Skipped before ``inclusion_probability`` (so it is never even
        # classified) and without drawing from *rng* (so excluded changes do not
        # perturb the seeded selection of the real changes around them).
        if is_self_chore_change(change):
            continue
        prob = inclusion_probability(change, base_rate)
        if prob <= 0.0:
            continue
        if rng.random() < prob:
            selected.append(change)
    return selected

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
        prob = inclusion_probability(change, base_rate)
        if prob <= 0.0:
            continue
        if rng.random() < prob:
            selected.append(change)
    return selected

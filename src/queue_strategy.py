"""Work-queue ordering strategies for :class:`~issue_store.IssueStore` (#10037).

Before this module the factory had no work picker: selection was oldest-first
FIFO, pinned at the GitHub API call (``sort=created`` / ``direction=asc``) and
consumed by a plain ``deque.popleft()``. ``IssueRefinementLoop`` (#9957) already
classifies the backlog into P0/P1/P2 labels, but nothing read them — a producer
without a consumer, while the oldest and least valuable issues sat permanently
at the front of every stage queue.

This module is the pure ordering engine: no I/O and no config object. It is
handed a clock (``now``) and a seeded RNG so every decision is reproducible in a
test; ``IssueStore`` owns the queues and the eligibility rules, and this decides
only the sequence in which queued work is *considered*.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Task


class QueueStrategy(StrEnum):
    """Selectable queue disciplines."""

    FIFO = "fifo"
    PRIORITY = "priority"
    WEIGHTED_MIX = "weighted_mix"


#: Priority labels, most urgent first. Written by ``IssueRefinementLoop``.
PRIORITY_BANDS: tuple[str, ...] = ("P0", "P1", "P2")

#: Band for issues carrying no priority label — the majority of fresh intake.
UNPRIORITISED = "none"

#: P0 means "the factory is broken right now" and preempts the mix outright
#: rather than taking a share of it.
_PREEMPT_BAND = "P0"

#: Bands that participate in the weighted draw, in declaration order.
_MIX_BANDS: tuple[str, ...] = ("P1", "P2", UNPRIORITISED)


@dataclass(frozen=True)
class BandWeights:
    """Relative share each band draws under ``weighted_mix``.

    A band with a positive weight cannot be starved: over many draws it wins a
    share proportional to its weight regardless of how much higher-band work
    arrives. Weights are validated positive at the config boundary, so the
    guarantee is a property of the type rather than of the default values.
    """

    p1: int
    p2: int
    unprioritised: int

    def of(self, band: str) -> int:
        """Weight for *band*; unknown bands draw nothing (never dropped)."""
        return {
            "P1": self.p1,
            "P2": self.p2,
            UNPRIORITISED: self.unprioritised,
        }.get(band, 0)


def band_of(task: Task) -> str:
    """The priority band *task* belongs to.

    An issue carrying several priority labels resolves to the most urgent one.
    Multi-labelling happens when a human adds a label that
    ``IssueRefinementLoop`` has already set differently; resolving upward fails
    safe, since the issue gets worked sooner rather than buried.
    """
    tags = set(task.tags)
    for band in PRIORITY_BANDS:
        if band in tags:
            return band
    return UNPRIORITISED


def _age_hours(task: Task, now: datetime) -> float | None:
    """Hours since *task* was opened, or ``None`` when it carries no timestamp.

    A missing or unparseable ``created_at`` is treated as "age unknown" rather
    than "brand new": the starvation guard simply cannot promote it, which fails
    safe (it never *forces* work in on bad data).
    """
    raw = task.created_at
    if not raw:
        return None
    text = str(raw)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        opened = datetime.fromisoformat(text)
    except ValueError:
        return None
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    return (now - opened).total_seconds() / 3600.0


def order_queue(
    tasks: list[Task],
    strategy: QueueStrategy,
    weights: BandWeights,
    *,
    rng: random.Random | None = None,
    now: datetime | None = None,
    starvation_threshold_hours: float | None = None,
) -> list[Task]:
    """Return *tasks* in the order *strategy* would have them considered.

    The result is always a permutation of the input. ``IssueStore`` rebuilds
    its deque from this list, so dropping a task here would silently lose
    queued work and duplicating one would double-dispatch an agent.

    ``rng`` (seed it for reproducibility), ``now`` and
    ``starvation_threshold_hours`` only affect ``weighted_mix``; the other
    disciplines are pure functions of *tasks*.
    """
    if strategy == QueueStrategy.FIFO:
        return list(tasks)

    banded = _partition(tasks)

    if strategy == QueueStrategy.PRIORITY:
        return [
            task for band in (*PRIORITY_BANDS, UNPRIORITISED) for task in banded[band]
        ]

    return _weighted_mix(
        banded,
        weights,
        rng if rng is not None else random.Random(),
        now,
        starvation_threshold_hours,
    )


def _partition(tasks: list[Task]) -> dict[str, list[Task]]:
    """Split *tasks* into per-band lists, preserving arrival order within each."""
    banded: dict[str, list[Task]] = {
        band: [] for band in (*PRIORITY_BANDS, UNPRIORITISED)
    }
    for task in tasks:
        banded[band_of(task)].append(task)
    return banded


def _weighted_mix(
    banded: dict[str, list[Task]],
    weights: BandWeights,
    rng: random.Random,
    now: datetime | None,
    threshold: float | None,
) -> list[Task]:
    """P0 first, then a starvation-valved weighted draw over the lower bands.

    Each iteration promotes at most one *starved* item (a lower-band task older
    than the threshold, oldest first) and then draws one item from a band chosen
    at random in proportion to its weight. Pacing promotion at one-per-draw is
    what keeps an all-aged backlog from collapsing ``weighted_mix`` back into
    FIFO: the age guard is a safety valve, not a second FIFO queue.
    """
    ordered: list[Task] = list(banded[_PREEMPT_BAND])
    remaining: dict[str, list[Task]] = {band: list(banded[band]) for band in _MIX_BANDS}

    def _remaining_count() -> int:
        return sum(len(items) for items in remaining.values())

    while _remaining_count() > 0:
        starved = _pop_most_starved(remaining, now, threshold)
        if starved is not None:
            ordered.append(starved)
        if _remaining_count() == 0:
            break
        drawn = _draw_one(remaining, weights, rng)
        if drawn is not None:
            ordered.append(drawn)

    return ordered


def _pop_most_starved(
    remaining: dict[str, list[Task]],
    now: datetime | None,
    threshold: float | None,
) -> Task | None:
    """Remove and return the oldest lower-band task past *threshold*, if any."""
    if now is None or threshold is None:
        return None
    best: tuple[float, str, int] | None = None
    for band in _MIX_BANDS:
        for index, task in enumerate(remaining[band]):
            age = _age_hours(task, now)
            if age is None or age < threshold:
                continue
            if best is None or age > best[0]:
                best = (age, band, index)
    if best is None:
        return None
    _, band, index = best
    return remaining[band].pop(index)


def _draw_one(
    remaining: dict[str, list[Task]],
    weights: BandWeights,
    rng: random.Random,
) -> Task | None:
    """Draw the front item of a weight-proportionally chosen non-empty band.

    A zero-weight band never wins the draw but is still drained (in arrival
    order) once every weighted band is empty, so the result stays a permutation
    — a zero weight means "only when nothing else is left", never "discard".
    """
    live = [
        (band, weights.of(band))
        for band in _MIX_BANDS
        if remaining[band] and weights.of(band) > 0
    ]
    if not live:
        for band in _MIX_BANDS:
            if remaining[band]:
                return remaining[band].pop(0)
        return None
    bands = [band for band, _ in live]
    band_weights = [weight for _, weight in live]
    chosen = rng.choices(bands, weights=band_weights, k=1)[0]
    return remaining[chosen].pop(0)

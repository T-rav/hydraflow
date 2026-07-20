"""Work-queue ordering strategies for :class:`~issue_store.IssueStore` (#10037).

Before this module the factory had no work picker: selection was oldest-first
FIFO, pinned at the GitHub API call (``sort=created`` / ``direction=asc``) and
consumed by a plain ``deque.popleft()``. ``IssueRefinementLoop`` (#9957) already
classifies the backlog into P0/P1/P2 labels, but nothing read them — a producer
without a consumer, while the oldest and least valuable issues sat permanently
at the front of every stage queue.

This module is the pure ordering engine: no I/O, no config object, no clock.
``IssueStore`` owns the queues and the eligibility rules; this decides only the
sequence in which queued work is *considered*.
"""

from __future__ import annotations

from dataclasses import dataclass
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

#: Bands that participate in the weighted draw, in draw order.
_MIX_BANDS: tuple[str, ...] = ("P1", "P2", UNPRIORITISED)


@dataclass(frozen=True)
class BandWeights:
    """How many items each band contributes per cycle of the weighted draw.

    A band with a positive weight cannot be starved: it receives a fixed share
    of every cycle regardless of how much higher-band work arrives. That is the
    whole reason ``weighted_mix`` exists alongside ``priority``, so weights are
    validated positive at the config boundary rather than here.
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


def order_queue(
    tasks: list[Task],
    strategy: QueueStrategy,
    weights: BandWeights,
) -> list[Task]:
    """Return *tasks* in the order *strategy* would have them considered.

    The result is always a permutation of the input. ``IssueStore`` rebuilds
    its deque from this list, so dropping a task here would silently lose
    queued work and duplicating one would double-dispatch an agent.
    """
    if strategy == QueueStrategy.FIFO:
        return list(tasks)

    banded = _partition(tasks)

    if strategy == QueueStrategy.PRIORITY:
        return [
            task for band in (*PRIORITY_BANDS, UNPRIORITISED) for task in banded[band]
        ]

    return _weighted_interleave(banded, weights)


def _partition(tasks: list[Task]) -> dict[str, list[Task]]:
    """Split *tasks* into per-band lists, preserving arrival order within each."""
    banded: dict[str, list[Task]] = {
        band: [] for band in (*PRIORITY_BANDS, UNPRIORITISED)
    }
    for task in tasks:
        banded[band_of(task)].append(task)
    return banded


def _weighted_interleave(
    banded: dict[str, list[Task]],
    weights: BandWeights,
) -> list[Task]:
    """Drain P0, then draw the remaining bands in the configured ratio."""
    ordered: list[Task] = list(banded[_PREEMPT_BAND])
    remaining = {band: list(banded[band]) for band in _MIX_BANDS}

    while True:
        progressed = False
        for band in _MIX_BANDS:
            for _ in range(weights.of(band)):
                if not remaining[band]:
                    break
                ordered.append(remaining[band].pop(0))
                progressed = True
        if not progressed:
            break

    # A zero-weight band means "only once nothing else is left", never
    # "discard" — without this the result would stop being a permutation.
    for band in _MIX_BANDS:
        ordered.extend(remaining[band])

    return ordered

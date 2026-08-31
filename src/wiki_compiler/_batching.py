"""One batching rule, shared by both compile paths (#11819).

``compile_topic`` grew a character-budgeted batcher when a 83KB ``patterns``
topic put the whole page in one 300s prompt. The tracked flow — the path
``RepoWikiLoop`` Phase 8 actually runs, and the one holding 4089 active
``patterns`` entries — never got it: ``_flow_synthesize`` joined every active
entry into a single prompt with no batching and no cap. The fix landed in N-1
of the N places that needed it.

Keeping the rule in one pure function is what makes that impossible to repeat:
a second copy is a second thing to fix, and the copy that is missed is the one
that has no test naming it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

T = TypeVar("T")


def batch_by_chars(
    items: Sequence[T], size_of: Callable[[T], int], budget: int
) -> list[list[T]]:
    """Split *items* into runs whose rendered size stays under *budget*.

    Budgets by CHARACTERS rather than item count: entries vary from a line to
    several paragraphs, so a fixed count still lets one prompt grow without
    bound — which is the defect, not a symptom of it.

    A single item larger than the whole budget still gets its own batch.
    Dropping it would silently lose wiki content, and a batch of one is the
    smallest prompt that can carry it; if that one call times out, the circuit
    breaker (#11823) bounds the cost.

    *size_of* must measure the SAME rendering the caller sends to the model.
    Measuring one string and sending another is how a budget stops bounding
    anything.
    """
    budget = max(budget, 1)
    batches: list[list[T]] = []
    current: list[T] = []
    used = 0
    for item in items:
        size = size_of(item)
        if current and used + size > budget:
            batches.append(current)
            current, used = [], 0
        current.append(item)
        used += size
    if current:
        batches.append(current)
    return batches

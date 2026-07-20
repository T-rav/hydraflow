"""Work-queue ordering strategies (#10037)."""

from __future__ import annotations

import pytest

from models import Task
from queue_strategy import (
    UNPRIORITISED,
    BandWeights,
    QueueStrategy,
    band_of,
    order_queue,
)


def _task(number: int, *tags: str) -> Task:
    return Task(id=number, title=f"issue {number}", tags=list(tags))


def _ids(tasks: list[Task]) -> list[int]:
    return [t.id for t in tasks]


DEFAULT_WEIGHTS = BandWeights(p1=3, p2=2, unprioritised=1)


# --- band_of ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (("P0",), "P0"),
        (("P1",), "P1"),
        (("P2",), "P2"),
        ((), UNPRIORITISED),
        (("hydraflow-ready",), UNPRIORITISED),
        (("hydraflow-ready", "P1"), "P1"),
    ],
)
def test_band_of_reads_the_priority_label(tags: tuple[str, ...], expected: str) -> None:
    assert band_of(_task(1, *tags)) == expected


def test_band_of_takes_the_most_urgent_when_an_issue_carries_several() -> None:
    # Mislabelled issues happen (a human adds P1 while IssueRefinementLoop has
    # already applied P2). Resolving to the most urgent band fails safe: the
    # issue gets worked sooner rather than being buried.
    assert band_of(_task(1, "P2", "P0", "P1")) == "P0"


# --- the permutation invariant --------------------------------------------


@pytest.mark.parametrize("strategy", list(QueueStrategy))
def test_ordering_is_a_permutation_of_the_input(strategy: QueueStrategy) -> None:
    # Load-bearing: IssueStore rebuilds its deque from this result, so dropping
    # or duplicating a task here silently loses queued work or double-dispatches
    # an agent. Every strategy must return exactly the input set.
    tasks = [
        _task(1, "P2"),
        _task(2),
        _task(3, "P0"),
        _task(4, "P1"),
        _task(5, "P1"),
        _task(6),
        _task(7, "P2"),
    ]
    ordered = order_queue(tasks, strategy, DEFAULT_WEIGHTS)

    assert sorted(_ids(ordered)) == sorted(_ids(tasks))
    assert len(ordered) == len(tasks)


def test_ordering_never_drops_a_band_whose_weight_is_absent() -> None:
    # A zero weight means "only when nothing else is left", never "discard".
    tasks = [_task(1, "P1"), _task(2, "P2"), _task(3)]
    ordered = order_queue(
        tasks, QueueStrategy.WEIGHTED_MIX, BandWeights(p1=1, p2=0, unprioritised=0)
    )

    assert sorted(_ids(ordered)) == [1, 2, 3]


# --- fifo ------------------------------------------------------------------


def test_fifo_preserves_the_incoming_order_exactly() -> None:
    # fifo is the escape hatch and the pre-#10037 behaviour pin: it must be a
    # faithful no-op so operators can revert ordering without a code change.
    tasks = [_task(1, "P2"), _task(2, "P0"), _task(3, "P1")]

    assert _ids(order_queue(tasks, QueueStrategy.FIFO, DEFAULT_WEIGHTS)) == [1, 2, 3]


# --- priority --------------------------------------------------------------


def test_priority_orders_by_band_then_keeps_arrival_order_within_a_band() -> None:
    tasks = [
        _task(1, "P2"),
        _task(2),
        _task(3, "P0"),
        _task(4, "P1"),
        _task(5, "P1"),
        _task(6, "P2"),
    ]

    assert _ids(order_queue(tasks, QueueStrategy.PRIORITY, DEFAULT_WEIGHTS)) == [
        3,
        4,
        5,
        1,
        6,
        2,
    ]


def test_priority_starves_the_lower_bands_under_continuous_p1_inflow() -> None:
    # Documents *why* priority is not the default. This is the failure mode
    # weighted_mix exists to avoid — asserted, not just described in a comment,
    # so the trade-off stays visible if someone flips the default.
    p2_backlog = [_task(100 + i, "P2") for i in range(5)]
    incoming_p1 = [_task(i, "P1") for i in range(20)]

    ordered = order_queue(
        p2_backlog + incoming_p1, QueueStrategy.PRIORITY, DEFAULT_WEIGHTS
    )

    assert all(band_of(t) == "P1" for t in ordered[:20])


# --- weighted_mix ----------------------------------------------------------


def test_weighted_mix_drains_p0_before_anything_else() -> None:
    # P0 is "the factory is broken right now" — it preempts the mix entirely
    # rather than taking a share of it.
    tasks = [_task(1, "P1"), _task(2, "P2"), _task(3, "P0"), _task(4, "P0")]

    ordered = order_queue(tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS)

    assert _ids(ordered)[:2] == [3, 4]


def test_weighted_mix_draws_bands_in_the_configured_ratio() -> None:
    tasks = [_task(i, "P1") for i in range(3)]
    tasks += [_task(10 + i, "P2") for i in range(2)]
    tasks += [_task(20)]

    ordered = order_queue(tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS)

    assert _ids(ordered) == [0, 1, 2, 10, 11, 20]


def test_weighted_mix_repeats_the_ratio_across_cycles() -> None:
    tasks = [_task(i, "P1") for i in range(6)]
    tasks += [_task(10 + i, "P2") for i in range(4)]
    tasks += [_task(20 + i) for i in range(2)]

    ordered = order_queue(tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS)

    assert _ids(ordered) == [0, 1, 2, 10, 11, 20, 3, 4, 5, 12, 13, 21]


def test_weighted_mix_keeps_lower_bands_moving_under_continuous_p1_inflow() -> None:
    # The headline guarantee, and the acceptance criterion from #10037: a band
    # with a positive weight cannot be starved no matter how much higher-band
    # work arrives.
    p2_backlog = [_task(100 + i, "P2") for i in range(5)]
    incoming_p1 = [_task(i, "P1") for i in range(50)]

    ordered = order_queue(
        p2_backlog + incoming_p1, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS
    )
    first_ten = ordered[:10]

    assert any(band_of(t) == "P2" for t in first_ten)


def test_weighted_mix_skips_bands_that_have_run_out() -> None:
    # An empty band must not stall the cycle or emit padding.
    tasks = [_task(i, "P1") for i in range(4)]
    tasks += [_task(20)]

    ordered = order_queue(tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS)

    assert _ids(ordered) == [0, 1, 2, 20, 3]


def test_weighted_mix_on_an_all_one_band_queue_is_plain_arrival_order() -> None:
    tasks = [_task(i, "P2") for i in range(4)]

    ordered = order_queue(tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS)

    assert _ids(ordered) == [0, 1, 2, 3]


def test_an_unhandled_strategy_raises_rather_than_silently_mixing() -> None:
    # Guards the "add a strategy, forget a branch" bug. Falling through to
    # weighted_mix would run the wrong discipline with no signal at all.
    with pytest.raises(ValueError, match="unhandled queue strategy"):
        order_queue([_task(1)], "not_a_strategy", DEFAULT_WEIGHTS)  # type: ignore[arg-type]


def test_empty_queue_orders_to_empty() -> None:
    for strategy in QueueStrategy:
        assert order_queue([], strategy, DEFAULT_WEIGHTS) == []

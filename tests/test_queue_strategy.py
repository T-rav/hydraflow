"""Work-queue ordering strategies (#10037)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from models import Task
from queue_strategy import (
    UNPRIORITISED,
    BandWeights,
    QueueStrategy,
    band_of,
    order_queue,
)

DEFAULT_WEIGHTS = BandWeights(p1=3, p2=2, unprioritised=1)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _task(number: int, *tags: str, age_hours: float | None = None) -> Task:
    created_at = ""
    if age_hours is not None:
        created_at = (NOW - timedelta(hours=age_hours)).isoformat()
    return Task(
        id=number, title=f"issue {number}", tags=list(tags), created_at=created_at
    )


def _ids(tasks: list[Task]) -> list[int]:
    return [t.id for t in tasks]


def _seeded() -> random.Random:
    return random.Random(0)


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
    ordered = order_queue(
        tasks,
        strategy,
        DEFAULT_WEIGHTS,
        rng=_seeded(),
        now=NOW,
        starvation_threshold_hours=168.0,
    )

    assert sorted(_ids(ordered)) == sorted(_ids(tasks))
    assert len(ordered) == len(tasks)


def test_ordering_never_drops_a_band_whose_weight_is_absent() -> None:
    # A zero weight means "only when nothing else is left", never "discard".
    tasks = [_task(1, "P1"), _task(2, "P2"), _task(3)]
    ordered = order_queue(
        tasks,
        QueueStrategy.WEIGHTED_MIX,
        BandWeights(p1=1, p2=0, unprioritised=0),
        rng=_seeded(),
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
    # Documents *why* priority is not the proposed default. This is the failure
    # mode weighted_mix exists to avoid — asserted, not just described in a
    # comment, so the trade-off stays visible if someone flips the default.
    p2_backlog = [_task(100 + i, "P2") for i in range(5)]
    incoming_p1 = [_task(i, "P1") for i in range(20)]

    ordered = order_queue(
        p2_backlog + incoming_p1, QueueStrategy.PRIORITY, DEFAULT_WEIGHTS
    )

    assert all(band_of(t) == "P1" for t in ordered[:20])


# --- weighted_mix: preemption ---------------------------------------------


def test_weighted_mix_drains_p0_before_anything_else() -> None:
    # P0 is "the factory is broken right now" — it preempts the mix entirely
    # rather than taking a share of it. Deterministic regardless of the RNG.
    tasks = [_task(1, "P1"), _task(2, "P2"), _task(3, "P0"), _task(4, "P0")]

    ordered = order_queue(
        tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS, rng=_seeded()
    )

    assert _ids(ordered)[:2] == [3, 4]


# --- weighted_mix: the ratio ----------------------------------------------


def test_weighted_mix_draws_bands_in_the_configured_ratio_over_many_draws() -> None:
    # The core of weighted_mix: over a large seeded sample the pick frequency of
    # each band tracks its weight (P1:P2:none = 3:2:1). Sampled from the prefix
    # where all three bands are still stocked, so no band has drained yet and
    # the empirical ratio is a clean read of the weights.
    per_band = 2000
    tasks = (
        [_task(i, "P1") for i in range(per_band)]
        + [_task(10_000 + i, "P2") for i in range(per_band)]
        + [_task(20_000 + i) for i in range(per_band)]
    )

    ordered = order_queue(
        tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS, rng=random.Random(1234)
    )

    prefix = ordered[:600]
    counts = dict.fromkeys(("P1", "P2", UNPRIORITISED), 0)
    for task in prefix:
        counts[band_of(task)] += 1
    fractions = {band: counts[band] / len(prefix) for band in counts}

    assert fractions["P1"] == pytest.approx(3 / 6, abs=0.06)
    assert fractions["P2"] == pytest.approx(2 / 6, abs=0.06)
    assert fractions[UNPRIORITISED] == pytest.approx(1 / 6, abs=0.06)


def test_weighted_mix_is_reproducible_for_a_given_seed() -> None:
    # No naked random in the take path: the same seed yields the same order, so
    # dispatch is replayable in a test and an incident post-mortem.
    tasks = [_task(i, "P1") for i in range(10)] + [
        _task(50 + i, "P2") for i in range(10)
    ]

    first = _ids(
        order_queue(
            tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS, rng=random.Random(7)
        )
    )
    second = _ids(
        order_queue(
            tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS, rng=random.Random(7)
        )
    )

    assert first == second


def test_weighted_mix_keeps_lower_bands_moving_under_continuous_p1_inflow() -> None:
    # The headline acceptance criterion from #10037: a band with a positive
    # weight cannot be starved no matter how much higher-band work arrives.
    p2_backlog = [_task(100 + i, "P2") for i in range(5)]
    incoming_p1 = [_task(i, "P1") for i in range(50)]

    ordered = order_queue(
        p2_backlog + incoming_p1,
        QueueStrategy.WEIGHTED_MIX,
        DEFAULT_WEIGHTS,
        rng=random.Random(3),
    )

    assert any(band_of(t) == "P2" for t in ordered[:10])


def test_weighted_mix_drains_a_zero_weight_band_last_but_never_drops_it() -> None:
    tasks = [_task(1, "P1"), _task(2, "P1"), _task(3, "P2"), _task(4)]

    ordered = order_queue(
        tasks,
        QueueStrategy.WEIGHTED_MIX,
        BandWeights(p1=3, p2=2, unprioritised=0),
        rng=_seeded(),
    )

    # The unweighted band (id 4) is emitted, and only after the weighted bands.
    assert set(_ids(ordered)) == {1, 2, 3, 4}
    assert _ids(ordered)[-1] == 4


def test_weighted_mix_on_an_all_one_band_queue_is_plain_arrival_order() -> None:
    tasks = [_task(i, "P2") for i in range(4)]

    ordered = order_queue(
        tasks, QueueStrategy.WEIGHTED_MIX, DEFAULT_WEIGHTS, rng=_seeded()
    )

    assert _ids(ordered) == [0, 1, 2, 3]


def test_empty_queue_orders_to_empty() -> None:
    for strategy in QueueStrategy:
        assert order_queue([], strategy, DEFAULT_WEIGHTS, rng=_seeded()) == []


# --- weighted_mix: age-based starvation guard -----------------------------


def test_weighted_mix_force_promotes_an_item_older_than_the_threshold() -> None:
    # An aged P2 among a flood of fresh P1s: the starvation valve pulls it to
    # the very front of the mix (after any P0) rather than leaving it to the
    # weighted draw, which under continuous P1 inflow could defer it for a long
    # time. Deterministic regardless of the RNG.
    aged_p2 = _task(999, "P2", age_hours=500.0)
    fresh_p1 = [_task(i, "P1", age_hours=1.0) for i in range(30)]

    ordered = order_queue(
        [aged_p2, *fresh_p1],
        QueueStrategy.WEIGHTED_MIX,
        DEFAULT_WEIGHTS,
        rng=random.Random(5),
        now=NOW,
        starvation_threshold_hours=168.0,
    )

    assert ordered[0].id == 999


def test_weighted_mix_promotes_the_oldest_starved_item_first() -> None:
    older = _task(1, "P2", age_hours=900.0)
    old = _task(2, "P2", age_hours=300.0)
    fresh = [_task(10 + i, "P1", age_hours=1.0) for i in range(10)]

    ordered = order_queue(
        [old, older, *fresh],
        QueueStrategy.WEIGHTED_MIX,
        DEFAULT_WEIGHTS,
        rng=random.Random(9),
        now=NOW,
        starvation_threshold_hours=168.0,
    )

    starved_positions = {t.id: i for i, t in enumerate(ordered)}
    assert starved_positions[1] < starved_positions[2]
    assert ordered[0].id == 1


def test_weighted_mix_without_a_clock_ignores_created_at_entirely() -> None:
    # When IssueStore does not supply now/threshold the guard is inert: the
    # timestamps have no effect and ordering is the pure weighted draw. Asserted
    # by equivalence to the same tasks with their timestamps stripped — for the
    # same seed the two orderings must be identical.
    aged = [_task(900 + i, "P2", age_hours=5000.0) for i in range(4)]
    fresh = [_task(i, "P1", age_hours=1.0) for i in range(10)]
    dateless_aged = [_task(900 + i, "P2") for i in range(4)]
    dateless_fresh = [_task(i, "P1") for i in range(10)]

    with_dates = _ids(
        order_queue(
            [*aged, *fresh],
            QueueStrategy.WEIGHTED_MIX,
            DEFAULT_WEIGHTS,
            rng=random.Random(2),
        )
    )
    without_dates = _ids(
        order_queue(
            [*dateless_aged, *dateless_fresh],
            QueueStrategy.WEIGHTED_MIX,
            DEFAULT_WEIGHTS,
            rng=random.Random(2),
        )
    )

    assert with_dates == without_dates


def test_weighted_mix_ignores_age_on_items_without_a_timestamp() -> None:
    # A missing created_at is "age unknown", not "infinitely old" — it must not
    # be force-promoted, or a data gap would silently invert the ordering. The
    # only tasks here are a no-timestamp P2 and fresh P1s, so no item qualifies
    # for promotion and the clocked ordering equals the pure draw.
    no_timestamp_p2 = _task(999, "P2")  # created_at == ""
    fresh_p1 = [_task(i, "P1", age_hours=1.0) for i in range(20)]

    with_clock = _ids(
        order_queue(
            [no_timestamp_p2, *fresh_p1],
            QueueStrategy.WEIGHTED_MIX,
            DEFAULT_WEIGHTS,
            rng=random.Random(4),
            now=NOW,
            starvation_threshold_hours=168.0,
        )
    )
    pure = _ids(
        order_queue(
            [no_timestamp_p2, *fresh_p1],
            QueueStrategy.WEIGHTED_MIX,
            DEFAULT_WEIGHTS,
            rng=random.Random(4),
        )
    )

    assert with_clock == pure

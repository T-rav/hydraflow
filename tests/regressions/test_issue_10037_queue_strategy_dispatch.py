"""Regression: order_queue fails loudly on an unhandled strategy (#10037).

``order_queue`` originally ended with a bare ``return _weighted_interleave(...)``,
so anything that was not ``fifo`` or ``priority`` was treated as
``weighted_mix``. Nothing invalid can reach it today — ``HydraFlowConfig``
validates the field and ``PATCH /api/control/config`` re-validates through
``model_validate`` and 422s on a bad value — but a *new* strategy added to the
``QueueStrategy`` enum without a matching branch would have been silently
dispatched as ``weighted_mix``.

That is the dangerous shape: the scheduler keeps running and picking work, just
under the wrong discipline, with no error, no log line, and every existing test
still green. This pins the loud failure so the fall-through cannot come back.
"""

from __future__ import annotations

import pytest

from models import Task
from queue_strategy import BandWeights, QueueStrategy, order_queue

_WEIGHTS = BandWeights(p1=3, p2=2, unprioritised=1)


def test_an_unhandled_strategy_raises_rather_than_silently_mixing() -> None:
    with pytest.raises(ValueError, match="unhandled queue strategy"):
        order_queue(
            [Task(id=1, title="issue 1")],
            "not_a_strategy",  # type: ignore[arg-type]
            _WEIGHTS,
        )


@pytest.mark.parametrize("strategy", list(QueueStrategy))
def test_every_declared_strategy_still_dispatches(strategy: QueueStrategy) -> None:
    # The other half of the guard: the raise must not be reachable for a
    # strategy that IS declared, or adding the guard would have broken a
    # working discipline instead of protecting it.
    tasks = [Task(id=1, title="a", tags=["P1"]), Task(id=2, title="b")]

    assert sorted(t.id for t in order_queue(tasks, strategy, _WEIGHTS)) == [1, 2]

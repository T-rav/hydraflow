"""Regression pins for the flow primitive (epic #10682, P0).

Load-bearing invariants the phase/worker refactors (P1-P3) will depend on:

1. **Checkpoint-per-node, in order.** Resume-from-checkpoint (ADR-0021) is only
   sound if every completed node is checkpointed exactly once, in walk order.
2. **Fail-closed on node failure** (ADR-0049): a raising node propagates and is
   NOT checkpointed, so a resume never skips past work that never completed.

If either invariant regresses, a converted phase could silently resume mid-node
or lose a step — the exact thrash class this epic exists to remove.
"""

from __future__ import annotations

from typing import Any

import pytest

from flows import Edge, Flow, Node

FlowState = dict[str, Any]


def _step(name: str):
    async def _run(state: FlowState) -> FlowState:
        state.setdefault("visited", []).append(name)
        return state

    return _run


async def test_checkpoint_fires_once_per_node_in_order() -> None:
    checkpoints: list[str] = []

    def checkpoint(name: str, _state: FlowState) -> None:
        checkpoints.append(name)

    flow = Flow(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[Edge("a", "b"), Edge("b", "c")],
        entry="a",
        checkpoint=checkpoint,
    )

    await flow.run({})

    assert checkpoints == ["a", "b", "c"]


async def test_raising_node_propagates_and_is_not_checkpointed() -> None:
    checkpoints: list[str] = []

    def checkpoint(name: str, _state: FlowState) -> None:
        checkpoints.append(name)

    async def boom(_state: FlowState) -> FlowState:
        raise RuntimeError("fail-closed")

    flow = Flow(
        nodes=[_node("a"), Node("boom", boom)],
        edges=[Edge("a", "boom")],
        entry="a",
        checkpoint=checkpoint,
    )

    with pytest.raises(RuntimeError, match="fail-closed"):
        await flow.run({})

    assert checkpoints == ["a"]


def _node(name: str) -> Node:
    return Node(name, _step(name))

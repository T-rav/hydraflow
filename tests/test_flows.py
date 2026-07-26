"""Unit tests for the in-framework flow (DAG) primitive (``src/flows``).

Covers the P0 contract of epic #10682: linear walks, conditional gate routing,
loop nodes that retry until a condition clears, per-node ``on_node`` + persistence
``checkpoint`` hooks, a fail-closed kill-switch, node-exception propagation,
resume-from-checkpoint, graph-validation errors, and the trivial JSONL
checkpoint adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flows import (
    Edge,
    Flow,
    FlowError,
    FlowResult,
    FlowValidationError,
    Node,
    jsonl_checkpoint,
)

FlowState = dict[str, Any]


# ---------------------------------------------------------------------------
# Node run helpers
# ---------------------------------------------------------------------------


def _appender(name: str):
    """Build a step ``run`` that records *name* in ``state['log']``."""

    async def _run(state: FlowState) -> FlowState:
        state.setdefault("log", []).append(name)
        return state

    return _run


async def _boom(state: FlowState) -> FlowState:
    raise RuntimeError("node blew up")


# ---------------------------------------------------------------------------
# Linear walk
# ---------------------------------------------------------------------------


class TestLinearFlow:
    async def test_runs_nodes_in_edge_order(self) -> None:
        flow = Flow(
            nodes=[
                Node("a", _appender("a")),
                Node("b", _appender("b")),
                Node("c", _appender("c")),
            ],
            edges=[Edge("a", "b"), Edge("b", "c")],
            entry="a",
        )

        result = await flow.run({})

        assert isinstance(result, FlowResult)
        assert result.state["log"] == ["a", "b", "c"]
        assert result.path == ["a", "b", "c"]
        assert result.terminal == "c"
        assert result.halted is False

    async def test_single_node_is_terminal(self) -> None:
        flow = Flow(nodes=[Node("only", _appender("only"))], edges=[], entry="only")

        result = await flow.run({})

        assert result.path == ["only"]
        assert result.terminal == "only"


# ---------------------------------------------------------------------------
# Gate routing
# ---------------------------------------------------------------------------


class TestGateRouting:
    def _gate_flow(self) -> Flow:
        async def classify(state: FlowState) -> FlowState:
            return state

        async def route_a(state: FlowState) -> FlowState:
            state["route"] = "a"
            return state

        async def route_b(state: FlowState) -> FlowState:
            state["route"] = "b"
            return state

        return Flow(
            nodes=[
                Node("classify", classify, kind="gate"),
                Node("route_a", route_a),
                Node("route_b", route_b),
            ],
            edges=[
                Edge("classify", "route_a", when=lambda s: s["kind"] == "a"),
                Edge("classify", "route_b", when=lambda s: s["kind"] == "b"),
            ],
            entry="classify",
        )

    async def test_first_matching_edge_wins(self) -> None:
        result = await self._gate_flow().run({"kind": "b"})

        assert result.state["route"] == "b"
        assert result.terminal == "route_b"
        assert result.path == ["classify", "route_b"]

    async def test_other_branch_taken_on_other_condition(self) -> None:
        result = await self._gate_flow().run({"kind": "a"})

        assert result.terminal == "route_a"
        assert result.path == ["classify", "route_a"]

    async def test_no_matching_edge_fails_closed(self) -> None:
        async def classify(state: FlowState) -> FlowState:
            return state

        async def only(state: FlowState) -> FlowState:
            return state

        flow = Flow(
            nodes=[Node("classify", classify, kind="gate"), Node("only", only)],
            edges=[Edge("classify", "only", when=lambda s: s["kind"] == "a")],
            entry="classify",
        )

        with pytest.raises(FlowError):
            await flow.run({"kind": "unmatched"})


# ---------------------------------------------------------------------------
# Loop node
# ---------------------------------------------------------------------------


class TestLoopNode:
    async def test_loop_retries_then_exits_on_condition(self) -> None:
        async def work(state: FlowState) -> FlowState:
            state["attempts"] = state.get("attempts", 0) + 1
            state.setdefault("log", []).append("work")
            return state

        flow = Flow(
            nodes=[
                Node("start", _appender("start")),
                Node("work", work, kind="loop"),
                Node("done", _appender("done")),
            ],
            edges=[
                Edge("start", "work"),
                # Loop back while the retry condition holds (deterministic:
                # this conditional edge is declared before the fallthrough).
                Edge("work", "work", when=lambda s: s["attempts"] < 3),
                Edge("work", "done"),
            ],
            entry="start",
        )

        result = await flow.run({})

        assert result.state["attempts"] == 3
        assert result.state["log"] == ["start", "work", "work", "work", "done"]
        assert result.path == ["start", "work", "work", "work", "done"]
        assert result.terminal == "done"

    async def test_max_steps_guards_runaway_loop(self) -> None:
        async def spin(state: FlowState) -> FlowState:
            return state

        flow = Flow(
            nodes=[Node("spin", spin, kind="loop")],
            edges=[Edge("spin", "spin", when=lambda _s: True)],
            entry="spin",
            max_steps=10,
        )

        with pytest.raises(FlowError):
            await flow.run({})


# ---------------------------------------------------------------------------
# Hooks: on_node + checkpoint
# ---------------------------------------------------------------------------


class TestHooks:
    async def test_on_node_and_checkpoint_invoked_once_per_node(self) -> None:
        # Snapshot the log list at call time (the flow state is shared + mutable,
        # so a shallow copy would alias the inner list and show later mutations).
        on_node_calls: list[tuple[str, list[str]]] = []
        checkpoint_calls: list[tuple[str, list[str]]] = []

        async def on_node(name: str, state: FlowState) -> None:
            on_node_calls.append((name, list(state.get("log", []))))

        def checkpoint(name: str, state: FlowState) -> None:
            checkpoint_calls.append((name, list(state.get("log", []))))

        flow = Flow(
            nodes=[Node("a", _appender("a")), Node("b", _appender("b"))],
            edges=[Edge("a", "b")],
            entry="a",
            on_node=on_node,
            checkpoint=checkpoint,
        )

        await flow.run({})

        assert [name for name, _ in on_node_calls] == ["a", "b"]
        assert [name for name, _ in checkpoint_calls] == ["a", "b"]
        # Hooks see post-node state at call time.
        assert on_node_calls[0][1] == ["a"]
        assert checkpoint_calls[1][1] == ["a", "b"]

    async def test_sync_and_async_hooks_both_supported(self) -> None:
        seen: list[str] = []

        def sync_checkpoint(name: str, _state: FlowState) -> None:
            seen.append(f"cp:{name}")

        async def async_on_node(name: str, _state: FlowState) -> None:
            seen.append(f"ev:{name}")

        flow = Flow(
            nodes=[Node("a", _appender("a"))],
            edges=[],
            entry="a",
            on_node=async_on_node,
            checkpoint=sync_checkpoint,
        )

        await flow.run({})

        assert seen == ["ev:a", "cp:a"]

    async def test_failed_node_is_not_checkpointed(self) -> None:
        checkpoints: list[str] = []

        def checkpoint(name: str, _state: FlowState) -> None:
            checkpoints.append(name)

        flow = Flow(
            nodes=[Node("a", _appender("a")), Node("boom", _boom)],
            edges=[Edge("a", "boom")],
            entry="a",
            checkpoint=checkpoint,
        )

        with pytest.raises(RuntimeError, match="node blew up"):
            await flow.run({})

        # 'a' checkpointed; the failing node is never checkpointed (fail-closed).
        assert checkpoints == ["a"]


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    async def test_halts_before_next_node(self) -> None:
        tripped = {"v": False}

        async def a(state: FlowState) -> FlowState:
            state.setdefault("log", []).append("a")
            tripped["v"] = True
            return state

        flow = Flow(
            nodes=[Node("a", a), Node("b", _appender("b"))],
            edges=[Edge("a", "b")],
            entry="a",
            kill_switch=lambda: tripped["v"],
        )

        result = await flow.run({})

        assert result.halted is True
        assert result.halted_at == "b"
        assert result.path == ["a"]
        assert result.state["log"] == ["a"]

    async def test_halts_before_entry_when_already_tripped(self) -> None:
        flow = Flow(
            nodes=[Node("a", _appender("a"))],
            edges=[],
            entry="a",
            kill_switch=lambda: True,
        )

        result = await flow.run({})

        assert result.halted is True
        assert result.halted_at == "a"
        assert result.path == []
        assert result.terminal is None


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class TestResume:
    async def test_resume_restarts_at_given_node(self) -> None:
        flow = Flow(
            nodes=[
                Node("a", _appender("a")),
                Node("b", _appender("b")),
                Node("c", _appender("c")),
            ],
            edges=[Edge("a", "b"), Edge("b", "c")],
            entry="a",
        )

        result = await flow.resume({"log": ["a"]}, from_node="b")

        assert result.path == ["b", "c"]
        assert result.state["log"] == ["a", "b", "c"]
        assert result.terminal == "c"

    async def test_resume_unknown_node_fails(self) -> None:
        flow = Flow(nodes=[Node("a", _appender("a"))], edges=[], entry="a")

        with pytest.raises(FlowValidationError):
            await flow.resume({}, from_node="ghost")


# ---------------------------------------------------------------------------
# Graph validation
# ---------------------------------------------------------------------------


class TestGraphValidation:
    async def test_unknown_entry_rejected(self) -> None:
        with pytest.raises(FlowValidationError, match="entry"):
            Flow(nodes=[Node("a", _appender("a"))], edges=[], entry="ghost")

    async def test_edge_with_unknown_src_rejected(self) -> None:
        with pytest.raises(FlowValidationError):
            Flow(
                nodes=[Node("a", _appender("a"))],
                edges=[Edge("ghost", "a")],
                entry="a",
            )

    async def test_edge_with_unknown_dst_rejected(self) -> None:
        with pytest.raises(FlowValidationError):
            Flow(
                nodes=[Node("a", _appender("a")), Node("b", _appender("b"))],
                edges=[Edge("a", "ghost")],
                entry="a",
            )

    async def test_unreachable_node_rejected(self) -> None:
        with pytest.raises(FlowValidationError, match="unreachable"):
            Flow(
                nodes=[
                    Node("a", _appender("a")),
                    Node("b", _appender("b")),
                    Node("orphan", _appender("orphan")),
                ],
                edges=[Edge("a", "b")],
                entry="a",
            )

    async def test_duplicate_node_name_rejected(self) -> None:
        with pytest.raises(FlowValidationError, match="duplicate"):
            Flow(
                nodes=[Node("a", _appender("a")), Node("a", _appender("a2"))],
                edges=[],
                entry="a",
            )

    async def test_no_nodes_rejected(self) -> None:
        with pytest.raises(FlowValidationError):
            Flow(nodes=[], edges=[], entry="a")


# ---------------------------------------------------------------------------
# JSONL checkpoint adapter
# ---------------------------------------------------------------------------


class TestJsonlCheckpointAdapter:
    async def test_appends_one_line_per_node(self, tmp_path: Path) -> None:
        path = tmp_path / "flow.jsonl"
        flow = Flow(
            nodes=[Node("a", _appender("a")), Node("b", _appender("b"))],
            edges=[Edge("a", "b")],
            entry="a",
            checkpoint=jsonl_checkpoint(path),
        )

        await flow.run({})

        lines = path.read_text().splitlines()
        records = [json.loads(line) for line in lines]
        assert [r["node"] for r in records] == ["a", "b"]
        assert records[1]["state"]["log"] == ["a", "b"]

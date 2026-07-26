"""In-framework flow (DAG) runtime — the P0 primitive of epic #10682.

HydraFlow's phases and multi-step background workers already contain implicit
DAGs (``decompose -> build -> verify -> gate``, ``classify -> screen -> route``)
crammed into single agentic prompts. This module makes that structure
**explicit and reusable**: typed :class:`Node` / :class:`Edge` / :class:`Flow`
with deterministic, gated control flow where the LLM is only ever the actuator
inside a node (same thesis as ADR-0099, made granular).

Design points:

* **Reuse, don't reinvent.** The runtime is thin because it stands on existing
  machinery via *injected* hooks — ``on_node`` wires to the event bus
  (:mod:`events`) for per-node telemetry, ``checkpoint`` wires to the
  persistence layer (ADR-0021) for resume. Keeping them injected keeps the
  primitive decoupled and unit-testable; a trivial JSONL checkpoint adapter
  lives in :mod:`flows.adapters`.
* **Fail-closed** (ADR-0049). A node exception propagates by default (never
  swallowed, never checkpointed). A gate with no matching outgoing edge raises
  rather than silently terminating. A per-flow ``kill_switch`` halts the walk
  cleanly (an observable :class:`FlowResult` with ``halted=True``), never a
  silent no-op.
* **Deterministic routing.** Outgoing edges are evaluated in declaration order;
  the first whose ``when`` is ``None`` or returns ``True`` wins. A node with no
  outgoing edge is terminal.
* **Validated at construction.** Unknown entry, dangling edge endpoints,
  duplicate node names, and unreachable nodes are rejected with clear errors.

Top-level pipeline state stays labels-as-state (ADR-0002); a flow is the
*intra-phase* structure living inside a single label transition.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# A flow's shared, mutable working state. Deliberately a plain dict so nodes,
# edge conditions, and checkpoint payloads can interoperate without a bespoke
# schema per phase.
FlowState = dict[str, Any]

NodeKind = Literal["step", "gate", "loop"]

#: A node body: transforms the shared state and returns it (async).
NodeRun = Callable[[FlowState], Awaitable[FlowState]]
#: An edge guard: decides whether this edge is taken for the current state.
EdgeCondition = Callable[[FlowState], bool]
#: A per-node side-effect hook (event emit / checkpoint). May be sync or async;
#: an awaitable return value is awaited.
NodeHook = Callable[[str, FlowState], Any]
#: Per-flow halt signal, polled before each node.
KillSwitch = Callable[[], bool]

# A ceiling on node executions to catch a non-terminating loop node. Opt-in via
# ``Flow(max_steps=...)``; ``None`` leaves the walk unbounded.
DEFAULT_MAX_STEPS: int | None = None


class FlowError(Exception):
    """A flow could not proceed (unroutable gate, runaway loop, bad resume)."""


class FlowValidationError(FlowError, ValueError):
    """A flow graph is structurally invalid (raised at construction)."""


@dataclass
class Node:
    """A single unit of work in a flow.

    A ``step`` transforms state and (typically) has one unconditional outgoing
    edge. A ``gate`` fans out: its outgoing :class:`Edge.when` conditions decide
    routing. A ``loop`` routes back to an earlier node while its retry condition
    holds, then falls through. ``kind`` is descriptive metadata — routing itself
    is always driven by outgoing edges — but it documents intent and lets
    telemetry/consumers distinguish node roles.
    """

    name: str
    run: NodeRun
    kind: NodeKind = "step"


@dataclass
class Edge:
    """A directed, optionally conditional transition between two nodes.

    ``when`` is ``None`` for an unconditional edge. When several edges leave a
    node, the first (in declaration order) whose ``when`` is ``None`` or returns
    ``True`` is taken — deterministic, first-match-wins.
    """

    src: str
    dst: str
    when: EdgeCondition | None = None


@dataclass
class FlowResult:
    """The outcome of a flow walk.

    ``path`` is the ordered list of node names actually executed (a loop node
    appears once per visit). ``terminal`` is the node that ended the walk
    (``None`` if the walk was halted by the kill-switch). ``halted`` /
    ``halted_at`` record a clean kill-switch stop and the node it stopped before.
    """

    state: FlowState
    path: list[str] = field(default_factory=list)
    terminal: str | None = None
    halted: bool = False
    halted_at: str | None = None


class Flow:
    """A validated DAG of :class:`Node` s connected by :class:`Edge` s.

    Construct with the node set, the edge set, and the ``entry`` node name.
    Production wires ``on_node`` to an event-bus emit and ``checkpoint`` to the
    persistence layer; both are kept injectable so the runtime stays decoupled
    and unit-testable. ``kill_switch`` (polled before each node) halts the walk
    fail-closed. ``max_steps`` optionally caps executions to catch a runaway
    loop.
    """

    def __init__(
        self,
        *,
        nodes: list[Node],
        edges: list[Edge],
        entry: str,
        on_node: NodeHook | None = None,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
        max_steps: int | None = DEFAULT_MAX_STEPS,
    ) -> None:
        self._nodes: dict[str, Node] = self._index_nodes(nodes)
        self._edges = list(edges)
        self.entry = entry
        self._on_node = on_node
        self._checkpoint = checkpoint
        self._kill_switch = kill_switch
        self._max_steps = max_steps

        # Outgoing edges per source, preserving declaration order for
        # deterministic first-match routing.
        self._outgoing: dict[str, list[Edge]] = {}
        for edge in self._edges:
            self._outgoing.setdefault(edge.src, []).append(edge)

        self._validate()

    # -- construction / validation ------------------------------------------

    @staticmethod
    def _index_nodes(nodes: list[Node]) -> dict[str, Node]:
        indexed: dict[str, Node] = {}
        for node in nodes:
            if node.name in indexed:
                raise FlowValidationError(f"duplicate node name: {node.name!r}")
            indexed[node.name] = node
        return indexed

    def _validate(self) -> None:
        if not self._nodes:
            raise FlowValidationError("flow has no nodes")
        if self.entry not in self._nodes:
            raise FlowValidationError(f"entry node {self.entry!r} is not a known node")
        for edge in self._edges:
            if edge.src not in self._nodes:
                raise FlowValidationError(
                    f"edge references unknown src node {edge.src!r}"
                )
            if edge.dst not in self._nodes:
                raise FlowValidationError(
                    f"edge references unknown dst node {edge.dst!r}"
                )
        self._reject_unreachable()

    def _reject_unreachable(self) -> None:
        reachable: set[str] = set()
        frontier = [self.entry]
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in self._outgoing.get(current, []):
                frontier.append(edge.dst)
        orphans = sorted(set(self._nodes) - reachable)
        if orphans:
            raise FlowValidationError(
                f"unreachable nodes (no path from entry {self.entry!r}): {orphans}"
            )

    # -- execution ----------------------------------------------------------

    async def run(self, state: FlowState) -> FlowResult:
        """Walk the flow from ``entry`` until a terminal node or a halt."""
        return await self._walk(state, self.entry)

    async def resume(self, state: FlowState, from_node: str) -> FlowResult:
        """Re-enter the walk at ``from_node`` (e.g. from a checkpoint).

        Checkpoints are written *after* a node completes, so pass the node you
        want to re-execute, or its successor to skip an already-completed node.
        """
        if from_node not in self._nodes:
            raise FlowValidationError(f"cannot resume at unknown node {from_node!r}")
        return await self._walk(state, from_node)

    async def _walk(self, state: FlowState, start: str) -> FlowResult:
        result = FlowResult(state=state)
        current: str | None = start
        steps = 0

        while current is not None:
            if self._kill_switch is not None and self._kill_switch():
                result.halted = True
                result.halted_at = current
                return result

            if self._max_steps is not None and steps >= self._max_steps:
                raise FlowError(
                    f"flow exceeded max_steps={self._max_steps} "
                    f"(runaway loop at node {current!r})"
                )

            node = self._nodes[current]
            # Fail-closed: a node exception propagates and the node is NOT
            # checkpointed — a resume can never skip past work that never
            # completed.
            state = await node.run(state)
            result.state = state
            result.path.append(current)
            steps += 1

            await self._emit(self._on_node, current, state)
            await self._emit(self._checkpoint, current, state)

            current = self._next(current, state)

        result.terminal = result.path[-1] if result.path else None
        return result

    def _next(self, current: str, state: FlowState) -> str | None:
        outgoing = self._outgoing.get(current, [])
        if not outgoing:
            return None  # terminal node
        for edge in outgoing:
            if edge.when is None or edge.when(state):
                return edge.dst
        # A node with outgoing edges but no matching condition is a routing gap.
        # Fail-closed rather than silently terminate.
        raise FlowError(
            f"no outgoing edge matched at node {current!r} — add a default "
            f"(unconditional) edge to make routing total"
        )

    @staticmethod
    async def _emit(hook: NodeHook | None, name: str, state: FlowState) -> None:
        if hook is None:
            return
        outcome = hook(name, state)
        if inspect.isawaitable(outcome):
            await outcome

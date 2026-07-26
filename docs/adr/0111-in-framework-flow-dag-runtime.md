# ADR-0111: In-framework flow (DAG) runtime for workers and phases

**Status:** Accepted
**Date:** 2026-07-26
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_flows.py

## Context

Two recurring failure modes trace to one root cause: *implicit control flow
crammed into a single agentic prompt.* Multi-step background workers that reason
and then verify in one prompt drift and hallucinate steps; the implement/build
worker thrashes on under-specified work (#10659, #10616) because the "did I
actually satisfy the spec / when do I stop" logic lives inside the prompt rather
than in explicit, gated edges — so an under-specified run burns the full 3600s
timeout and retries instead of aborting to a human.

HydraFlow already contains the ingredients of a flow engine — it just expresses
them ad-hoc, per-phase, in prose and bespoke code: `decompose -> build ->
verify -> gate` (implement), `classify -> screen -> touchpoint-expand -> route`
(triage), the plan-review council, the adversarial-retry loop. What is missing
is not a runtime — it is *making that structure explicit and reusable.* Adopting
LangGraph was considered and rejected (design proposal,
`docs/proposals/in-framework-flows-for-workers-and-phases.md`): HydraFlow has
already reinvented most of its value, and a second orchestration paradigm would
compete with the label state machine, the event bus, and the convergence
ledger. Epic #10682 is the umbrella; this ADR records the P0 foundation.

## Decision

Introduce a small, typed, in-`src/` flow (DAG) primitive — `src/flows/` — and,
in later phases (P1-P3), re-express the multi-step workers and pipeline phases
as flows on it. **No feature flags**: the full test pyramid (unit + MockWorld +
sandbox e2e) is the safety net, held green before each cutover.

The runtime is deliberately thin because it stands on existing machinery through
*injected* hooks:

- **`src/flows/flow.py:Node`** — `name`, an async `run(state) -> state`, and a
  descriptive `kind ∈ {step, gate, loop}`. A `step` transforms the shared state;
  a `gate` fans out via its outgoing edge conditions; a `loop` routes back to an
  earlier node while a retry condition holds, then falls through. Routing is
  always driven by outgoing edges — `kind` documents intent and lets telemetry
  distinguish node roles.
- **`src/flows/flow.py:Edge`** — `src`, `dst`, optional `when(state) -> bool`.
  When several edges leave a node they are evaluated in declaration order and
  the first whose `when` is `None` or returns `True` is taken: deterministic,
  first-match-wins routing.
- **`src/flows/flow.py:Flow`** — constructed with `nodes`, `edges`, and an
  `entry` name, plus injected `on_node` and `checkpoint` hooks, an optional
  `kill_switch`, and an optional `max_steps` runaway guard. `run(state)` walks
  `entry` → edges, executing each node and invoking the two hooks after it,
  until a node has no outgoing edge (terminal). `resume(state, from_node)`
  re-enters the walk at a checkpointed node.
- **`src/flows/flow.py:FlowResult`** — final `state`, the ordered `path` of node
  names executed, the `terminal` node, and a `halted` / `halted_at` pair
  recording a clean kill-switch stop.

**Reuse, don't reinvent.** The hooks are kept injectable so the primitive stays
decoupled and unit-testable, and so production wires them to existing systems
rather than new ones:

- **Checkpoints → persistence (ADR-0021).** `checkpoint(node, state)` fires
  after each completed node; resume restarts from the last one.
  `src/flows/adapters.py:jsonl_checkpoint` is the trivial, self-contained
  adapter, appending one crash-safe, secret-scrubbed JSONL record per node via
  `file_util.append_jsonl` (ADR-0085).
- **Per-node telemetry → the event bus.** `on_node(node, state)` fires after
  each node; production wires it to an `events.EventBus` emit. Choosing the
  concrete `EventType`/payload is a phase-conversion (P1+) concern, so the P0
  event hook is left injectable rather than shipped as an adapter.

**Fail-closed (ADR-0049).** A node exception propagates by default — never
swallowed, and the failing node is never checkpointed, so a resume can never
skip past work that never completed. A gate whose outgoing edges all evaluate
false raises rather than silently terminating (a routing gap is a bug, not a
terminal state). A per-flow `kill_switch`, polled before each node, halts the
walk cleanly and observably (`FlowResult.halted=True`) — never a silent no-op.

**Validated at construction.** `Flow` rejects an unknown `entry`, duplicate node
names, dangling edge endpoints, and nodes unreachable from `entry`, each with a
clear error.

The LLM is only ever the actuator *inside* a node; the control flow between
nodes is deterministic (same thesis as ADR-0099, made granular). The top-level
pipeline state stays labels-as-state (ADR-0002): a flow is the *intra-phase*
structure that lives inside a single label transition, never a replacement for
the label state machine.

## Non-goals

P0 wires the primitive into no real worker or phase — that is P1 (one background
worker, proof), P2 (the implement phase, highest value, adding the no-progress
early-abort gate that replaces the 3600s thrash), and P3 (plan → review →
triage). Parallel/fan-out node execution, a bespoke state schema per phase, and
a config-flag kill-switch are out of scope; the kill-switch is an injected
callable so a call site may back it with any signal.

## Consequences

New workers and phases gain a shared vocabulary — typed nodes, explicit gated
edges, checkpoint/resume, per-node telemetry — instead of re-deriving control
flow in prose per phase. The councils, gates, and retries that phases already
contain become reusable `gate`/`loop` nodes (one `adversarial_review` node
shared by plan, implement, and review instead of three bespoke copies). The cost
is one new module plus the discipline, enforced here, that the phase-execution
contract is a flow: deterministic routing, fail-closed gates, a checkpoint after
every completed node. `tests/test_flows.py` and
`tests/regressions/test_issue_10682_flows.py` pin the load-bearing invariants
(checkpoint-per-node in order; fail-closed on node failure and unroutable gate;
kill-switch halt; construction-time graph validation).

## Related

- Epic #10682 — in-framework flows (decompose workers + phases).
- Proposal: `docs/proposals/in-framework-flows-for-workers-and-phases.md`.
- ADR-0021 (persistence) — checkpoint/resume substrate.
- ADR-0049 (kill-switch convention) — fail-closed halt.
- ADR-0002 (labels as state machine) — the inter-phase state; flows are
  intra-phase.
- ADR-0099 — deterministic control, LLM-as-actuator; this makes it granular.
- ADR-0094–0098 (convergence gates), ADR-0105 (decompose-to-converge) — the
  loop/gate nodes a converted phase reuses.

# Flows for multi-step workers — HydraFlow methodology

> **Status:** Stable (extracted 2026-07-26 from epic #10682, the in-framework
> flow rollout: P0 primitive → P1 wiki-compiler → P2 implement → P3 plan/review/
> triage → P4 this playbook)
> **Scope:** How to build a new multi-step-with-verification worker or pipeline
> phase as an explicit `Flow` (DAG) instead of cramming its control flow into a
> single agentic prompt or a hand-rolled retry/route loop.

This document is the **playbook** behind [ADR-0111](../adr/0111-in-framework-flow-dag-runtime.md)
(the in-framework flow/DAG runtime). It is intentionally **methodology, not
code**: the runtime lives in `src/flows/`, and the five reference conversions
live in the phase modules. The code follows this playbook; the playbook
survives the code.

**The default:** a new multi-step-with-verification worker starts as a `Flow`.
The four pipeline phases (implement, plan, review, triage) plus the
wiki-compilation background worker are the reference implementations. Copy the
one closest to your shape; `_build_implement_flow` (in
`implement_phase/_flow.py`) is
the canonical worked example.

---

## 1. When to use a flow (and when not)

A flow makes control flow **explicit, gated, and reusable**. Reach for it when
the worker is *multi-step with verification* — it reasons, then checks its own
work, then decides whether to retry, escalate, or finish. That "did I actually
satisfy the spec / when do I stop" decision is exactly what drifts and thrashes
when it lives inside a prompt (the root cause of #10659 / #10616).

| Shape | Build it as | Why |
|---|---|---|
| Multi-step **with verification** (decompose → act → verify → gate) | **`Flow`** | Stop/route logic becomes deterministic gated edges, not prompt prose |
| Already a gate/loop/ensemble | **Reuse the shared node** | e.g. adversarial-review, convergence-gate, touchpoint-expand |
| One-shot transform (reason once, emit) | **Keep the prompt** | transcript-summary, term-proposer, adr-review, triage-honeypot — a flow buys nothing |

If in doubt, ask: *does this worker ever loop, retry, or route based on the
result of its own earlier step?* If yes → flow. If it is a pure
input→LLM→output transform → prompt.

The top-level pipeline state stays **labels-as-state** ([ADR-0002](../adr/0002-labels-as-state-machine.md)).
A flow is the *intra-phase* structure living inside a single label transition —
never a replacement for the label state machine.

---

## 2. The primitive (`src/flows/`)

Three typed pieces, all in `flow.py`:

- **`Node(name, run, kind)`** — `run` is an `async (state) -> state` body.
  `kind ∈ {step, gate, loop}` is descriptive metadata only (routing is always
  driven by edges); it documents intent and lets telemetry distinguish roles.
- **`Edge(src, dst, when=None)`** — a directed, optionally conditional
  transition. When several edges leave a node they are evaluated in
  **declaration order** and the **first** whose `when` is `None` or returns
  `True` wins. First-match-wins, deterministic.
- **`Flow(nodes=…, edges=…, entry=…, checkpoint=…, kill_switch=…, on_node=…,
  max_steps=…)`** — validated at construction (rejects unknown entry, duplicate
  names, dangling endpoints, unreachable nodes). `run(state)` walks `entry` →
  edges until a node has no outgoing edge (terminal). `resume(state, from_node)`
  re-enters the walk at a checkpointed node.

The runtime is thin by design — it stands on existing machinery through
*injected* hooks, so production wires them to systems that already exist rather
than new ones:

- **`checkpoint(node, state)`** → persistence ([ADR-0021](../adr/0021-persistence-architecture-and-data-layout.md)).
  Fires after each completed node; resume restarts from the last one.
  `flows.adapters.jsonl_checkpoint` is the trivial, secret-scrubbed adapter.
- **`on_node(node, state)`** → the event bus, for per-node telemetry.
- **`kill_switch()`** → a fail-closed halt ([ADR-0049](../adr/0049-trust-loop-kill-switch-convention.md)),
  polled before each node; a halt is observable (`FlowResult.halted=True`),
  never a silent no-op.

**Fail-closed everywhere.** A node exception propagates (never swallowed, never
checkpointed — a resume can't skip past work that never completed). A gate whose
outgoing edges all evaluate false **raises** rather than silently terminating: a
routing gap is a bug, not a terminal state. Make routing *total* — every gate
needs a default (unconditional) edge.

---

## 3. The three load-bearing conventions

These are what kept all five conversions **behaviour-preserving**. Copy them.

### 3.1 The delegation seam — nodes wrap, they do not rewrite

A node body **delegates to the existing step-method**. The conversions did not
re-implement `evaluate`, `_run_and_post_review`, `_write_plan_records`,
`BugReproducer.reproduce`, or the push/PR tail — they wrapped each as a node:

```python
async def _flow_build(self, state: FlowState) -> FlowState:
    """The actuator node — delegates to the existing implementation call."""
    result = await self._run_implementation(
        state["issue"], state["branch"], state["idx"], state["review_feedback"]
    )
    state["result"] = result
    return state
```

The node's job is to read from and write to the shared `state` dict and call the
real worker method. This is why converting a phase is *low blast radius*: the
step-methods stay live node bodies, so their behaviour, tests, and error
handling are untouched. **Do not delete a step-method just because the top-level
orchestrator got thinner — it is almost certainly still a live node body.**

### 3.2 `state['_stop']` + a shared `_flow_stopped` edge for fail-closed exits

Every early exit — an admission-control short-circuit, an attempt-cap
escalation, a no-progress abort, a "nothing to do" close — sets
`state['_stop'] = True` and writes the final `result` into state, then returns.
A single module-level edge guard routes any stopped node straight to the
terminal sink:

```python
def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to done."""
    return bool(state.get("_stop"))

# ...in the builder, first-match-wins puts the stop edge before the happy edge:
Edge("decompose", "done", when=_flow_stopped),
Edge("decompose", "no-progress-abort"),
```

Because the stop edge is declared *first*, a stopped node skips the rest of the
graph and lands on `done`. This replaces the tangle of early `return`s in the
old straight-line orchestrator with one uniform, greppable convention.

### 3.3 One terminal sink + a thin builder/runner entry

Every path — the happy walk and each fail-closed exit — ends at one `done` node
(a no-op join point) carrying the final `result`. The public entry method keeps
its signature and return type; internally it just builds and runs the flow:

```python
async def _worker_inner(self, idx, issue, branch) -> WorkerResult:
    flow = self._build_implement_flow()
    outcome = await flow.run(self._initial_flow_state(idx, issue, branch))
    return outcome.state["result"]
```

Keeping the builder a method (not a module constant) lets `checkpoint` /
`kill_switch` be injected per-call for tests, and lets a second entry re-enter
the *same* graph via `resume`. The implement phase uses this: post-build
handling re-enters at the `screen` node (`flow.resume(state, "screen")`) so
there is a single source of truth for the screen → verify → gate branches.

---

## 4. Recipe — convert a worker to a flow

1. **Draw the DAG first**, as an ASCII diagram in the module docstring (see the
   top of `implement_phase/_common.py`). Name the nodes; mark which edges are
   conditional and on what.
2. **Identify the actuator boundary** — the single node that spends the LLM/agent
   call. Everything else is deterministic routing. In implement it is `build`;
   in plan it is `draft`; in triage it is `classify`.
3. **Split the old straight-line body at each decision point** into node methods
   (`_flow_<name>`), each delegating to the existing step-method (§3.1).
4. **Encode every early `return` as `state['_stop']`** + the shared
   `_flow_stopped` edge (§3.2). Encode every branch as a gated edge, declaration
   order = precedence.
5. **Add a `done` sink** and a thin builder + entry (§3.3).
6. **Hold the full test pyramid green — no feature flag.** Parity *is* the
   safety net: every existing unit test, the MockWorld scenario suite
   (`-m scenario_loops`), and the phase's sandbox e2e must stay green across the
   cutover. This is a control-flow-made-explicit refactor, not a behaviour
   change; if a test goes red, the graph is wrong, not the test.
7. **Flag, don't wire, parity boundaries.** If wiring an existing-but-unused
   helper into a node would *add* behaviour (a new escalation, an extra
   comment), note it in the commit and leave it out — that is a separate,
   behaviour-changing PR. (P3a did exactly this with `_handle_plan_failure`.)

---

## 5. Reference implementations

| Worker | Builder | Graph (abbreviated) |
|---|---|---|
| **implement** (canonical) | `_build_implement_flow` | `decompose → no-progress-abort → build → screen → (spec-verify \| open-pr) → gate → done` |
| **plan** | `_build_plan_flow` | `prepass → surface → draft → ensemble → route → write-records → gate → ready → done` |
| **review** | `_build_review_flow` | `guards → pre-review → pre-flight → review → post-review → gate → (route →) cleanup → done` |
| **triage** | `_build_triage_flow` | `classify → route → record → reproduce → swap → done` |
| **wiki-compilation** (P1) | `_build_compile_flow` | `extract → verify → synthesize → validate → done` |

Start from the row whose shape matches yours. The ensemble (`loop`) and
convergence-gate (`gate`) nodes are shared across phases — reuse them rather
than building a bespoke copy.

---

## 6. Related

- [ADR-0111](../adr/0111-in-framework-flow-dag-runtime.md) — the decision this
  playbook operationalizes.
- [ADR-0099](../adr/0099-orchestration-as-a-control-system.md) — deterministic control,
  LLM-as-actuator; a flow makes it granular.
- [ADR-0002](../adr/0002-labels-as-state-machine.md) — the inter-phase state;
  flows are intra-phase.
- [ADR-0021](../adr/0021-persistence-architecture-and-data-layout.md) /
  [ADR-0049](../adr/0049-trust-loop-kill-switch-convention.md) — the checkpoint and
  kill-switch seams the primitive injects.
- `docs/proposals/in-framework-flows-for-workers-and-phases.md` — the original
  design proposal (LangGraph considered and rejected).

# In-framework flows (DAG) for background workers and pipeline phases

**Status:** proposal (2026-07-26). **Decision inputs (operator):** use HydraFlow's *own* framework for flows — **not LangGraph**; and decompose not just the one-shot background workers but the **main pipeline phases (triage → plan → implement → review)** into explicit sub-flows.

## The gap

Two failure modes trace to the same root — *implicit control flow crammed into one big agentic prompt*:

1. **Background workers** that do multi-step reasoning + verification in a single prompt drift and hallucinate steps.
2. **The build worker (implement) thrashes** on under-specified work (see #10659, #10616): one giant agentic session with no explicit `decompose → build → verify → gate` structure runs the full 3600s timeout and retries, because the "when do I stop / did I actually satisfy the spec" logic lives inside the prompt instead of in gated edges.

HydraFlow already *has* the ingredients of a flow engine — it just expresses them ad-hoc, per-phase, in prose and bespoke code rather than a shared primitive.

## Direction (decided)

Build a **small in-framework flow primitive** — typed nodes, explicit edges/gates, shared state — and express the multi-step workers and the pipeline phases as flows on it. **No new external dependency (no LangGraph):** HydraFlow has already reinvented most of LangGraph's value and a second orchestration paradigm would compete with it. What we're missing is not a runtime — it's *making the existing structure explicit and reusable.*

### Reuse, don't reinvent
The flow primitive is thin because it stands on existing machinery:
- **State/checkpoints** → persistence architecture (ADR-0021).
- **Node telemetry / observability** → the event bus (each node emits start/finish/verdict).
- **Loop/convergence nodes** → convergence ledger + gates (ADR-0094–0098), adversarial-retry loop, decompose-to-converge (ADR-0105).
- **Top-level state machine stays** labels-as-state (ADR-0002). Flows are the *intra-phase* structure; labels remain the *inter-phase* one. Flows never replace the label state machine — they live inside a single label transition.

## Inventory + classification

**One-shot transforms — KEEP as prompts** (a flow is pure ceremony): `transcript_summary`, `term_proposer`, `adr_review`, `triage_honeypot`.

**Multi-step-with-verification background workers — flow candidates:** wiki-compilation/rot (`extract → verify shipped-claims → synthesize → validate provenance`), adr-conformance reasoning, adr-drift-resolver.

**Pipeline phases — sub-flow candidates** (each already contains an implicit DAG):
- **triage:** `classify → injection-screen → touchpoint-expand → validate → route`.
- **plan:** `draft → plan-review council (N reviewers, parallel) → touchpoint re-review → converge/route-back`.
- **implement:** `decompose → build-step → spec-compliance verify → gate(retry ≤3 | route-to-HITL) → open-PR`. *(This is the highest-value conversion — the thrash lives here.)*
- **review:** `review → adversarial-retry → convergence gate → approve | request-changes | HITL`.

The phases' existing councils/gates/retries **become reusable flow nodes** — e.g. one `adversarial_review` node shared by plan, implement, and review instead of three bespoke implementations.

## The flow primitive (foundation)

Minimal, typed, in-`src/`:
- `Node`: `name`, `kind ∈ {llm, pure, gate, loop}`, `run(state) -> state` (async). An `llm` node is one focused prompt/provider-call; a `gate` node returns the next edge id; a `loop` node wraps convergence/retry with the ledger.
- `Edge`: `from`, `to`, optional `condition(state) -> bool`.
- `Flow.run(initial_state)`: walks nodes per edges, **checkpoints state after each node** (ADR-0021), **emits an event per node** (event bus), and is resumable from the last checkpoint. Deterministic control flow; the LLM is only ever the actuator inside a node — same thesis as ADR-0099, made granular.
- Fail-closed defaults (ADR-0049) at every gate; kill-switch per flow.

## Work plan (incremental — never big-bang the load-bearing phases)

**P0 — Flow primitive + tests (foundation).** `src/flows/` with `Node`/`Edge`/`Flow`, checkpointing on the persistence layer, per-node event emission, a kill-switch, and the full unit set. **Ships a new ADR** (this changes the phase-execution contract). No worker/phase touched yet.

**P1 — Convert one background worker (proof).** wiki-compilation → `extract → verify → synthesize → validate` on the primitive. Behind a flag; MockWorld parity vs the current one-shot; cut over at parity. Validates the primitive on a low-blast-radius worker.

**P2 — Convert the implement phase (highest value).** Re-express implement as `decompose → build → spec-verify → gate` — the fix for the #10659 thrash: the gate, not the prompt, decides retry-vs-HITL, and a no-progress node aborts early instead of burning 3600s. Behind a flag, **full test pyramid + MockWorld + sandbox e2e parity**, cut over only at parity.

**P3 — Convert plan, then review, then triage.** Each as a sub-flow reusing the P0 nodes (the plan-review council and the adversarial-retry become shared `loop`/`gate` nodes). One phase per PR, behind a flag, parity-gated, in that order (plan's council is the cleanest next; review's adversarial gate reuses P2's; triage last).

**P4 — Retire the bespoke per-phase control code** once each phase is on the primitive and parity holds; document the pattern so new workers start as flows.

## Guardrails
- **Migrate behind flags with parity gates; never big-bang.** Each phase keeps its old path until the flow path proves behavior parity on unit + MockWorld + sandbox e2e.
- **ADR required at P0** (phase-execution contract change) and referenced by each migration.
- **Scope discipline:** P0 + P1 + P2 is the committed first cut; P3/P4 are sequenced follow-ups, not this epic's blast radius.

## Acceptance
- The flow primitive + tests land with a checkpoint/resume + per-node telemetry story on existing machinery.
- One background worker and the implement phase run on flows with demonstrated behavior parity behind a flag, then cut over.
- A no-progress/early-abort gate replaces the implement thrash (a run that isn't converging aborts to HITL, not to the 3600s timeout).
- An ADR records the flow-runtime decision; the remaining phases have a sequenced, parity-gated path.

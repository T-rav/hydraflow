---
id: "01JZ9FK3C0M02HYR42BF22W0B2"
name: "FitnessScorecardLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/fitness_scorecard_loop.py:FitnessScorecardLoop"
aliases: ["fitness scorecard", "fitness scorecard loop", "loop fitness scorecard"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-30T00:00:00.000000+00:00"
updated_at: "2026-06-30T00:00:00.000000+00:00"
---

## Definition

Read-only caretaker loop (ADR-0029) that produces the per-loop fitness scorecard on a configurable cadence (default 86400 s). Each tick it builds one `FitnessContext` per registered loop, calls every loop's `loop_fitness(ctx)`, persists results to `fitness.jsonl`, regenerates `docs/arch/generated/loop-fitness.md`, and emits a `LOOP_FITNESS_UPDATE` event. Mutates no loop state, so it sits off the ADR-0046 recursion ladder. Kill-switch via `enabled_cb("fitness_scorecard")` per ADR-0049. (ADR-0093)

## Invariants

- Kill-switch is via `enabled_cb("fitness_scorecard")` at the top of `_do_work()` (ADR-0049).
- The loop is read-only: it calls `loop_fitness()` on peer loops but changes no loop config or state.
- Declares its own fitness as `HOUSEKEEPING` — it produces no GitHub proposals or artifacts that have an acceptance lifecycle.

---
id: "01JZ9FK3C0M03HYR42BF33W0C3"
name: "FitnessContext"
kind: "value_object"
bounded_context: "caretaker"
code_anchor: "src/loop_fitness.py:FitnessContext"
aliases: ["fitness context", "loop fitness context"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-30T00:00:00.000000+00:00"
updated_at: "2026-06-30T00:00:00.000000+00:00"
---

## Definition

Frozen, data-only Pydantic model that is the **sole input** to any `loop_fitness()` call. Carries the evaluation window (`window_start`, `window_end`), this loop's `BACKGROUND_WORKER_STATUS` events pre-filtered to the window, a snapshot list of `IssueRecord`s relevant to the loop, and optional per-loop cost. Contains no live GitHub client. The purity constraint (ADR-0093 §2) requires that `loop_fitness()` reads only from `ctx` — no network, no clock, no mutable self state — which lets the same function score live history now and replayed history in the future optimizer.

## Invariants

- Carries no live client or callable; the model is frozen (`model_config = {"frozen": True}`).
- `issues` is a snapshot list of `IssueRecord` rows; each loop attributes its own artifacts by querying this list for its label.
- The same `FitnessContext` instance that powers the live scorecard can power an offline optimizer replay — that equivalence is the design invariant this type enforces.

---
id: "01JZ9FK3C0M01HYR42BF11W0A1"
name: "LoopFitness"
kind: "value_object"
bounded_context: "caretaker"
code_anchor: "src/loop_fitness.py:LoopFitness"
aliases: ["loop fitness", "loop fitness score", "fitness result"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-30T00:00:00.000000+00:00"
updated_at: "2026-06-30T00:00:00.000000+00:00"
---

## Definition

The result of calling a background loop's `loop_fitness(ctx)` method for one evaluation window. Carries `kind` (`SCORED` or `HOUSEKEEPING`), an optional normalized `score` in [0, 1] valid only for intra-loop trend comparison, raw `components` for diagnosis, `sample_count`, and a `Confidence` signal (`OK` or `INSUFFICIENT_DATA`) keyed off `sample_count` vs a per-loop threshold. Produced by every `BaseBackgroundLoop` subclass; consumed by `FitnessScorecardLoop` and persisted to `fitness.jsonl`. (ADR-0093)

## Invariants

- `score` is normalized 0–1 and valid **only for intra-loop use** (trend over time, or intra-loop config ranking). Cross-loop comparison of `score` is architecturally invalid.
- When `kind` is `HOUSEKEEPING`, `score` is always `None`; `components` carries raw counters.
- `confidence` is `INSUFFICIENT_DATA` when `sample_count` is below the loop's `min_samples` threshold; `score` is `None` in that case regardless of `kind`.

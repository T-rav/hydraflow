---
id: "01KWDRENTS7VACCW9PDA7Y488H"
name: "Governor"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/base_background_loop.py:LoopDeps"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393501+00:00"
updated_at: "2026-07-01T02:34:42.393502+00:00"
---

## Definition

The saturation limiter and safety interlock that bounds every Actuator regardless of Controller intent. LoopDeps carries a loop's per-cycle safety controls — the kill switch (enabled_cb) and the watchdog timeout bound (timeout_cb); the wider Governor role (concurrency caps, credit holds) is realized elsewhere, by the max_workers/max_planners semaphores and the credit-exhaustion signal. The v2 Governor generalizes these into an explicit capacity-and-safety authority.

## Invariants

- The Governor can veto or throttle any actuation; a Controller cannot override it.

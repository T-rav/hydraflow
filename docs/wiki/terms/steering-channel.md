---
id: "01KWN0R5WY93KMBF8CWG9MPFH9"
name: "SteeringChannel"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/human_steering_loop.py:HumanSteeringLoop"
aliases: []
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "depends_on", "target": "01KWN0R5WY93KMBF8CWG9MPFHB"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-03T22:14:23.000000+00:00"
updated_at: "2026-07-18T18:45:11.335019+00:00"
---

## Definition

The continuous Human reference-input path (ADR-0099 §6 surface #4, closed by ADR-0103): a live, per-issue channel from an operator's GitHub comments into the running pipeline, replacing the discrete single-shot `pending_correction` + suspend/wake mechanism. The channel has a sensor half (`HumanSteeringLoop` parses `/steer`, `/pause`, `/resume`, `/redo`, `/abort` comment directives into a persisted `SteeringState` each tick) and an actuator half (the orchestrator's `_apply_human_steering` enacts the latest state at the next phase boundary — skip, park, redo, or fold guidance into the next prompt). The two halves never share a process step: the sensor only senses, the actuator only enacts, so the orchestrator stays thin.

## Invariants

- The channel applies at phase boundaries only; it never interrupts a running phase mid-flight (the only mid-phase stop is the fleet-wide `SIGKILL`).
- Declarative directives (`/steer`, `/pause`, `/resume`) are recomputed latest-wins from the full comment history every tick; imperative directives (`/redo`, `/abort`) fire at most once, gated by a per-issue `created_at` high-water-mark so a re-tick cannot replay them.

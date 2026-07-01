---
id: "01KWDRENTS7VACCW9PDA7Y488C"
name: "Sensor"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:MetricsSnapshot"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393454+00:00"
updated_at: "2026-07-01T02:34:42.393455+00:00"
---

## Definition

Any component that measures the current state of the Plant and emits a signal a Controller can read — deterministic (drift detectors, lint) or LLM-based (spec/review judges). MetricsSnapshot is the canonical aggregate reading.

## Invariants

- A Sensor observes; it does not mutate the Plant.

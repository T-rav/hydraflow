---
id: "01KWDRENTS7VACCW9PDA7Y488B"
name: "Plant"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:StateData"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393265+00:00"
updated_at: "2026-07-01T02:34:42.393430+00:00"
---

## Definition

The process an orchestration loop drives and observes: the repository plus an issue's lifecycle. Its durable, observable state is captured in StateData (and, in v2, the ConvergenceLedger). Controllers act on the Plant through Actuators; Sensors read it.

## Invariants

- The Plant is only mutated through an Actuator, never by a Controller directly.

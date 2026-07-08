---
id: "01KWDRENTS7VACCW9PDA7Y488G"
name: "Actuator"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/base_runner.py:BaseRunner"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393494+00:00"
updated_at: "2026-07-01T02:34:42.393495+00:00"
---

## Definition

The component that applies a Controller's action to the Plant: dispatches an agent runner, opens a PR, swaps a pipeline label. BaseRunner is the canonical actuator; PRManager realizes the PR-creation and label-swap actions.

## Invariants

- Every Actuator action is subject to the Governor's saturation and safety limits.

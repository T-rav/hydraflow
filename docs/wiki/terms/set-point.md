---
id: "01KWDRENTS7VACCW9PDA7Y488D"
name: "Set-point"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/issue_store.py:IssueStoreStage"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393466+00:00"
updated_at: "2026-07-01T02:34:42.393467+00:00"
---

## Definition

The desired state an orchestration loop drives toward — an issue reaching its terminal pipeline stage (the MERGED value of the IssueStoreStage state space), or a regulator holding a quantity at zero. A first-class converged flag arrives with the v2 ConvergenceLedger.

## Invariants

- The Set-point is the loop's target, not its current state (that is the Sensor reading).

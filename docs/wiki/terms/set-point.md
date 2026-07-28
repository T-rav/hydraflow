---
id: "01KWDRENTS7VACCW9PDA7Y488D"
name: "Set-point"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/issue_store.py:IssueStoreStage"
aliases: []
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KYM003P7D6GN4KSS1X9RBEXQ"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393466+00:00"
updated_at: "2026-07-28T19:17:03.630439+00:00"
---

## Definition

The desired state an orchestration loop drives toward — an issue reaching its terminal pipeline stage (the MERGED value of the IssueStoreStage state space), or a regulator holding a quantity at zero. A first-class converged flag arrives with the v2 ConvergenceLedger.

## Invariants

- The Set-point is the loop's target, not its current state (that is the Sensor reading).

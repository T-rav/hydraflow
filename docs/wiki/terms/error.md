---
id: "01KWDRENTS7VACCW9PDA7Y488E"
name: "Error"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/harness_insights.py:FailureRecord"
aliases: []
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KT3WKPR5MN8QJ14CF77W6K3"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393475+00:00"
updated_at: "2026-07-18T19:31:17.682213+00:00"
---

## Definition

The gap between Set-point and measured state that a Controller acts to reduce: unresolved review concerns, a REQUEST_CHANGES verdict, route-backs, or a recorded FailureRecord. On main the signal is largely binary; a continuous per-issue error is a known-open surface.

## Invariants

- Error is derived (Set-point minus measured state), never authored directly.

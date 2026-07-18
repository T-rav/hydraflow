---
id: "01KWDRENTS7VACCW9PDA7Y488F"
name: "Controller"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/issue_store.py:IssueStore"
aliases: []
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K3"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393487+00:00"
updated_at: "2026-07-18T20:13:56.561118+00:00"
---

## Definition

The component that converts Error into a control action — which unit to act on next and how hard. HydraFlow has a supervisory controller (which issue to admit/route, today FIFO in IssueStore) and an inner controller (the per-issue gate decision, e.g. the review_advisor PostVerifyResult APPROVE/VETO).

## Invariants

- A Controller decides; it does not itself touch the Plant (that is the Actuator).

---
id: "01KWDRENTS7VACCW9PDA7Y488F"
name: "Controller"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/issue_store.py:IssueStore"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T02:34:42.393487+00:00"
updated_at: "2026-07-01T02:34:42.393488+00:00"
---

## Definition

The component that converts Error into a control action — which unit to act on next and how hard. HydraFlow has a supervisory controller (which issue to admit/route, today FIFO in IssueStore) and an inner controller (the per-issue gate decision, e.g. the review_advisor PostVerifyResult APPROVE/VETO).

## Invariants

- A Controller decides; it does not itself touch the Plant (that is the Actuator).

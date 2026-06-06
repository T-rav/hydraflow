---
id: "01KT3WKPR5MN8QJ14CF77W6K2"
name: "ReviewInsightStorePort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:ReviewInsightStorePort"
aliases: ["review insight store port", "review insight port"]
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KTANBHSTGWNRXS6M142101ED"}, {"kind": "depends_on", "target": "01KTANCQNKWYRJ5ETEVNAMEY5A"}, {"kind": "depends_on", "target": "01KTBHAP0E4RHCFZVEC1P12QQM"}]
evidence: ["01KQNYW9WM9NY7XJ0DNPVW4GDS", "01KQP0XFBGMB32VFGNPV8GZ26W", "01KRBX2N4QP7VW8FGH3J5YD0M3"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-06T01:07:16.635794+00:00"
---

## Definition

Hexagonal port for persisting and querying recurring reviewer-feedback patterns. Implemented by `review_insights.ReviewInsightStore`. `ReviewPhase` injects this port to record each review outcome and to query which feedback categories have been seen often enough to inject mandatory guidance blocks into the next agent prompt. The port decouples `ReviewPhase` from the JSONL file-storage backend.

## Invariants

- Pure Protocol — no implementation, no state.
- Methods cover the full lifecycle: `append_review` writes a new record, `load_recent` reads recent history, `get_proposed_categories` and `mark_category_proposed` gate category escalation, and `record_proposal`, `load_proposal_metadata`, and `update_proposal_verified` track whether a proposed mandatory block reduced the pattern.

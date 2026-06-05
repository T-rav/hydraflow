---
id: "01KTANBHSTGWNRXS6M142101ED"
name: "HITLItem"
kind: "entity"
bounded_context: "builder"
code_anchor: "src/models.py:HITLItem"
aliases: ["hitl item", "human-in-the-loop item", "operator review item"]
related: [{"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KTAN07XWECDDWZ84AQD4HFC7"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:11:27.290714+00:00"
updated_at: "2026-06-05T01:11:27.290716+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:11:27.290666+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

An HITLItem (Human-In-The-Loop Item) is a domain entity representing a pending operator decision point within the pipeline — a named work item that requires human review and explicit resolution before automated processing can continue. It carries a lifecycle status (PENDING → PROCESSING → RESOLVED) tracked via HITLItemStatus, is cached and surfaced by GitHubCacheLoop, and is referenced across the port boundary by PRPort, PRManager, and all major infrastructure ports. Engineers name it explicitly in design discussions: 'This action produces a new HITLItem' or 'The pipeline is blocked on an unresolved HITLItem.'

## Invariants

- Status transitions are monotonically forward: PENDING → PROCESSING → RESOLVED; no backward transitions are defined.
- Every HITLItem in the system is reflected in the GitHubCacheLoop's HITL item snapshot, making it visible to all consumers without direct API calls.

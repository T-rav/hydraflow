---
id: "01KYABD5XVX4ZXFXT3Z76KMQZ0"
name: "HITLItem"
kind: "entity"
bounded_context: "caretaker"
code_anchor: "src/models.py:HITLItem"
aliases: ["hitl issue", "hitl queue item", "escalation item"]
related: [{"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QGA4VF2GJDCW3ZVKNBPMY"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-24T15:20:22.204037+00:00"
updated_at: "2026-07-24T15:20:22.204044+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-24T15:20:22.203368+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

HITLItem is the entity representing a single Human-In-The-Loop escalation: an issue (and, if one exists, its associated PR) that has stalled and requires human review or intervention. It carries identity (issue number), the escalation cause, a lifecycle status (HITLItemStatus: pending, processing, resolved), and pointers to the underlying issue/PR/branch. PRManager assembles HITLItems from raw GitHub issues, GitHubDataCache serves them via GitHubCacheLoop.get_hitl_items(), PRPort exposes list_hitl_items() as the formal port method for fetching them, and PRUnstickerLoop (ADR-0077) consumes them to drive autonomous resolution of stuck HITL-labeled PRs before falling back to a human.

## Invariants

- status defaults to HITLItemStatus.PENDING and transitions through PROCESSING to RESOLVED
- issue is the required identity field; pr/pr_url/branch are populated only when a PR is associated
- cause records the escalation reason that routed the issue into the HITL queue

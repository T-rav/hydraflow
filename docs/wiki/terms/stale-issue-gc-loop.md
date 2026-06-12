---
id: "01KR9A3F20M01PGF32CF88W9A8"
name: "StaleIssueGCLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/stale_issue_gc_loop.py:StaleIssueGCLoop"
aliases: ["stale issue gc loop", "stale hitl gc loop", "hitl stale closer"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
<<<<<<< HEAD
evidence: []
=======
evidence: ["01KQP0R43781VJFJ9HZRWQCZPA"]
>>>>>>> origin/staging
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
<<<<<<< HEAD
updated_at: "2026-06-12T04:17:13.434460+00:00"
=======
updated_at: "2026-06-12T04:20:14.221533+00:00"
>>>>>>> origin/staging
---

## Definition

Caretaker loop that auto-closes stale HITL escalation issues (ADR-0029). Scope is specifically open issues carrying the configured HITL label that have been inactive beyond `stale_issue_threshold_days`. Posts a farewell comment, then closes. Caps at 10 closures per cycle to avoid GitHub rate-limiting. Distinct from `StaleIssueLoop`, which handles stale general issues with no HydraFlow lifecycle label — the two loops share only the `BaseBackgroundLoop` framework and have zero business-logic overlap.

## Invariants

- Maximum 10 issues closed per tick to respect GitHub rate limits.
- Only closes issues carrying the HITL label (`config.hitl_label`), not general issues.
- `StaleIssueGCLoop` and `StaleIssueLoop` are fully separate; do not conflate them.

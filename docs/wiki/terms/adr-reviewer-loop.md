---
id: "01KRBL0F20M01PGF32CF88W9B7"
name: "ADRReviewerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/adr_reviewer_loop.py:ADRReviewerLoop"
aliases: ["ADR reviewer loop", "adr council review loop", "adr review loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-12T04:17:13.434460+00:00"
---

## Definition

Caretaker loop that polls for ADRs in `Proposed` status and runs council reviews via `ADRCouncilReviewer`. The loop is intentionally thin: all review logic and output formatting live in `ADRCouncilReviewer`, keeping tick scheduling and business logic separately testable. Review interval is `config.adr_review_interval`.

## Invariants

- The loop delegates entirely to `ADRCouncilReviewer.review_proposed_adrs()`; no review logic lives in the loop itself.
- Kill-switch is via `enabled_cb("adr_reviewer")` and `config.adr_reviewer_loop_enabled` (ADR-0049).

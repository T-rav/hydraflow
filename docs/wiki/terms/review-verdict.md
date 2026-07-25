---
id: "01KYBV9N8VSTKDRVDFC0FE40ZM"
name: "ReviewVerdict"
kind: "value_object"
bounded_context: "builder"
code_anchor: "src/models.py:ReviewVerdict"
aliases: ["review verdict", "review decision", "review outcome"]
related: [{"kind": "depends_on", "target": "01KY4QGA4VF2GJDCW3ZVKNBPMY"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C1"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-25T05:17:18.491284+00:00"
updated_at: "2026-07-25T05:17:18.491288+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-25T05:17:18.491187+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

The closed-set outcome of a reviewer agent's evaluation of a pull request — APPROVE, REQUEST_CHANGES, or COMMENT. It is the terminal decision produced by the review phase (src/reviewer.py), submitted as a formal GitHub PR review via PRManager.submit_review, and consumed downstream to gate auto-merge eligibility (DependabotMergeLoop's human/bot shepherd path only merges on ReviewVerdict.APPROVE) and to drive review-insight analytics (review_insights.py filters records by verdict != APPROVE).

## Invariants

- Exactly one of APPROVE, REQUEST_CHANGES, or COMMENT — no other values are valid
- PRManager.submit_review maps each verdict to its corresponding gh CLI review flag (--approve / --request-changes / --comment)
- Only ReviewVerdict.APPROVE authorizes DependabotMergeLoop's shepherd path to proceed to merge

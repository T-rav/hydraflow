---
id: "01KYBDB1SVS3N2J40H4AE1ST9D"
name: "ReviewVerdict"
kind: "value_object"
bounded_context: "builder"
code_anchor: "src/models.py:ReviewVerdict"
aliases: ["reviewer verdict", "review outcome", "pr review decision"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QGA4VF2GJDCW3ZVKNBPMY"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9C1"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-25T01:13:24.027258+00:00"
updated_at: "2026-07-25T01:13:24.027262+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-25T01:13:24.027183+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 3
---

## Definition

The enumerated verdict a reviewer agent renders on a pull request — approve, request-changes, or comment. Submitted as a formal GitHub PR review via PRPort.submit_review / PRManager.submit_review, and read downstream by merge automation such as DependabotMergeLoop to decide whether a PR is eligible for auto-merge, gating the review→merge stage of the pipeline.

## Invariants

- Three-valued StrEnum: APPROVE, REQUEST_CHANGES, COMMENT
- Submitted as a formal GitHub PR review via PRPort.submit_review / PRManager.submit_review
- Only ReviewVerdict.APPROVE is treated as merge-eligible by downstream automation (e.g. DependabotMergeLoop's CI-green shepherd path)

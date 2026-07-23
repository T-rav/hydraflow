---
id: 0236
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.800828+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Join factory pipeline metrics by issue_number, not pr_number

When correlating factory metrics or reviews across pipeline tables, join on `issue_number` rather than `pr_number`.

Example: a PR can be closed and recreated with a new number; `issue_number` is stable across the full lifecycle.

**Why:** `pr_number` changes when PRs are recycled; joining on it silently drops or duplicates records for any issue where the PR was recreated.

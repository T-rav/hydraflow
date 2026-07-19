---
id: 0202
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.158031+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Join factory pipeline metrics by issue_number, not pr_number

When correlating factory metrics or reviews across pipeline tables, join on `issue_number` rather than `pr_number`.

Example: a PR can be closed and recreated with a new number; `issue_number` is stable across the full lifecycle.

**Why:** `pr_number` changes when PRs are recycled; joining on it silently drops or duplicates records for any issue where the PR was recreated.

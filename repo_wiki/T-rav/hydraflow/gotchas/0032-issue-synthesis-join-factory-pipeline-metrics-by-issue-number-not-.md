---
id: 0032
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.696672+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Join factory pipeline metrics by `issue_number`, not `pr_number`

When correlating factory metrics or reviews across pipeline tables, join on `issue_number` rather than `pr_number`.

Example: a PR can be closed and recreated with a new number; `issue_number` is stable across the full lifecycle.

**Why:** `pr_number` changes when PRs are recycled; joining on it silently drops or duplicates records for any issue where the PR was recreated.

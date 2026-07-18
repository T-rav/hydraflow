---
id: 0066
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:59:29.451098+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Join factory pipeline metrics by `issue_number`, not `pr_number`

When correlating factory metrics or reviews across pipeline tables, join on `issue_number` rather than `pr_number`.

Example: a PR can be closed and recreated with a new number; `issue_number` is stable across the full lifecycle.

**Why:** `pr_number` changes when PRs are recycled; joining on it silently drops or duplicates records for any issue where the PR was recreated.

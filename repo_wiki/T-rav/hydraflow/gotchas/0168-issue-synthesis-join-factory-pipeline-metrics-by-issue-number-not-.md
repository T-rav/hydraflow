---
id: 0168
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.954098+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Join factory pipeline metrics by issue_number, not pr_number

When correlating factory metrics or reviews across pipeline tables, join on `issue_number` rather than `pr_number`.

Example: a PR can be closed and recreated with a new number; `issue_number` is stable across the full lifecycle.

**Why:** `pr_number` changes when PRs are recycled; joining on it silently drops or duplicates records for any issue where the PR was recreated.

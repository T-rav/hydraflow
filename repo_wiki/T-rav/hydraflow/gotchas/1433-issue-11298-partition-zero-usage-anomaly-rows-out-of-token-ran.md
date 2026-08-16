---
id: 1433
topic: gotchas
source_issue: 11298
source_phase: plan
created_at: 2026-08-16T05:49:45.238819+00:00
status: active
corroborations: 1
---

# Partition zero-usage anomaly rows out of token ranking

Zero-usage rows with nonzero transcript bytes must be excluded from `issues` and `phase_share` and reported in a separate `anomalies` block (count + bytes). In `src/token_report.py`, `_bucket_stats` checks the `usage_anomaly` field with a status fallback for rows missing that field.

**Why:** A single 5 MB failed spawn with no usage data can dominate the entire phase ranking, making the report useless for cost allocation and causing downstream PRs to be sized on phantom data.

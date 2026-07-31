---
id: 1233
topic: patterns
source_issue: 10898
source_phase: plan
created_at: 2026-07-31T11:06:20.726235+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Merge dormant records onto existing stats entries, never create new

Tally non-terminal conclusions per check name, then merge onto checks that already have ≥1 terminal attempt. A check seen only as skipped/cancelled yields no `JobStats` entry.

- Record order does not matter (merge after first pass)
- `JobStats` default for the dormant counter is 0 for backward compatibility

**Why:** Without merge-not-increment, dormancy could conjure a stats entry for a never-run check, polluting findings with phantom checks that never had a terminal outcome.

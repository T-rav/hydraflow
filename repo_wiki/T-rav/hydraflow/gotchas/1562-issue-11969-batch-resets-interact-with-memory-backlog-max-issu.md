---
id: 1562
topic: gotchas
source_issue: 11969
source_phase: plan
created_at: 2026-09-01T11:15:55.080413+00:00
status: active
corroborations: 1
---

# Batch resets interact with memory_backlog_max_issues_per_tick cap

Resetting more than `memory_backlog_max_issues_per_tick` (default 5) mirrors in one tick does NOT file them all individually. The cap applies post-reset: the first N file individually, the remainder are dedup-recorded and folded into one overflow summary issue.

Example: resetting 20 stale pins → 5 file individually, 15 land in one overflow summary.

**Why:** Operators must confirm before merge that a single-tick mass re-file is acceptable; the cap silently transforms the expected 20-issue blast into a 6-issue burst.

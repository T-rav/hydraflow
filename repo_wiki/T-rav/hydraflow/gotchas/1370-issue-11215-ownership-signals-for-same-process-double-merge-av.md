---
id: 1370
topic: gotchas
source_issue: 11215
source_phase: plan
created_at: 2026-08-15T05:13:01.079657+00:00
status: active
corroborations: 1
---

# Ownership signals for same-process double-merge avoidance

Before resuming a merge on a periodic tick, require BOTH `n not in reviewer.active_issues` AND `n not in store.is_active(n)`. The `handle_approved` MERGED guard is a backstop, not a substitute.

- `reviewer.active_issues` is in-memory and empty right after boot (safe for the restart case).
- On a periodic tick it is the only same-process ownership signal; a live builder could be mid-merge.
- Both checks are required, not either/or.

**Why:** Relying on only one signal races a live reviewer on the periodic tick and can double-merge; the MERGED guard catches the duplicate but produces noise and label churn.

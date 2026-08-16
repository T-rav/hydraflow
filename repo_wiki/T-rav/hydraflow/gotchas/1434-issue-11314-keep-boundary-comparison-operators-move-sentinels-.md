---
id: 1434
topic: gotchas
source_issue: 11314
source_phase: plan
created_at: 2026-08-16T07:29:20.234606+00:00
status: active
corroborations: 1
---

# Keep boundary comparison operators; move sentinels out of domain

When fixing a boundary collision at a valid threshold (e.g., `plan_review_min_complexity=10`), change the sentinel value, not the comparison operator. In `src/plan_phase.py`, introduce `UNKNOWN_COMPLEXITY = 11` (above the `le=10` ceiling) rather than changing `_tier_eligible`'s `>` to `>=`.

**Why:** Altering a shared comparison operator like `>` to `>=` breaks tiering at every threshold, not just the edge case. Moving the sentinel out of the domain isolates the fix to the unknown-complexity path.

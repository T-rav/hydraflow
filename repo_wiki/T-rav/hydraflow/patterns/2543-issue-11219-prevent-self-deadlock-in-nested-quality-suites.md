---
id: 2543
topic: patterns
source_issue: 11219
source_phase: plan
created_at: 2026-08-15T06:20:11.277017+00:00
status: superseded
corroborations: 1
superseded_by: 2666
---

# Prevent self-deadlock in nested quality suites

Set an inheritance flag like `HYDRAFLOW_SUITE_LOCK_HELD` in the environment when acquiring the suite lock in `scripts/quality_mutex.py`. If a nested command inherits this flag, allow it to proceed without attempting to reacquire the lock.

**Why:** Without re-entrancy detection, factory-invoked suites that trigger nested `make quality` targets will self-deadlock.

---
id: 2789
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:02.171449+00:00
status: superseded
corroborations: 1
supersedes: 2666
superseded_by: 2918
---

# Prevent self-deadlock in nested quality suites

Set an inheritance flag like `HYDRAFLOW_SUITE_LOCK_HELD` in the environment when acquiring the suite lock in `scripts/quality_mutex.py`. If a nested command inherits this flag, allow it to proceed without attempting to reacquire the lock.

**Why:** Without re-entrancy detection, factory-invoked suites that trigger nested `make quality` targets will self-deadlock.

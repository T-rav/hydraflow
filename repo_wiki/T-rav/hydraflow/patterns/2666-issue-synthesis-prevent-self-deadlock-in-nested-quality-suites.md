---
id: 2666
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:49.067321+00:00
status: active
corroborations: 1
supersedes: 2543
---

# Prevent self-deadlock in nested quality suites

Set an inheritance flag like `HYDRAFLOW_SUITE_LOCK_HELD` in the environment when acquiring the suite lock in `scripts/quality_mutex.py`. If a nested command inherits this flag, allow it to proceed without attempting to reacquire the lock.

**Why:** Without re-entrancy detection, factory-invoked suites that trigger nested `make quality` targets will self-deadlock.

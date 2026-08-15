---
id: 3045
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.526955+00:00
status: active
corroborations: 1
supersedes: 2918
---

# Prevent self-deadlock in nested quality suites

Set an inheritance flag like `HYDRAFLOW_SUITE_LOCK_HELD` in the environment when acquiring the suite lock in `scripts/quality_mutex.py`. If a nested command inherits this flag, allow it to proceed without attempting to reacquire the lock. See also: [patterns] — Host-wide flock mutex for full quality suites.

**Why:** Without re-entrancy detection, factory-invoked suites that trigger nested `make quality` targets will self-deadlock.

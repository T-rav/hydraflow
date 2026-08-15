---
id: 1381
topic: gotchas
source_issue: 11219
source_phase: plan
created_at: 2026-08-15T06:20:11.277006+00:00
status: active
corroborations: 1
---

# Degrade-open advisory locks to prevent stale locks

Make advisory locks in `scripts/quality_mutex.py` degrade-open by default past the wait deadline. If `HYDRAFLOW_SUITE_LOCK_WAIT` expires, run the suite anyway and print `[suite-lock DEGRADED]`. Provide a `strict` mode for opt-in hard failures.

**Why:** Stale locks or unexpected holder crashes must never block the factory gate indefinitely.

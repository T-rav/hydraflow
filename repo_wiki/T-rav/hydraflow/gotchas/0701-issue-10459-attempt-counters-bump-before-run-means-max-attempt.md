---
id: 0701
topic: gotchas
source_issue: 10459
source_phase: plan
created_at: 2026-07-24T12:58:41.700672+00:00
status: active
corroborations: 1
---

# Attempt counters bump-before-run means max-attempt is always unprotected (known gap)

Both `get_issue_attempts` and `get_auto_agent_attempts` in this repo are incremented *before* the run starts and cleared on close/success. A retry-window guard written as `0 < attempts < max_attempts` therefore never protects the final attempt (`attempts == max`), since that run is in-flight but the bound excludes it. This is an accepted, theoretical residual race in `src/workspace_gc_loop.py` — not a regression to fix inline; closing it fully requires a live session lock/heartbeat, tracked as a `hydraflow-find` follow-up rather than blocking the fix.

**Why:** documents why the last-attempt gap is intentional scope-out, so future readers don't re-flag it as an unfixed bug.

---
id: 2645
topic: testing
source_issue: 11238
source_phase: plan
created_at: 2026-08-15T09:37:15.548528+00:00
status: active
corroborations: 1
---

# Orchestrator credit-pause API is pinned: extend, don't rename

`_pause_for_credits` must keep returning the `(affected, terminate)` tuple and accept the `terminate_runners` kwarg. Extend with new parameters; do not rename or restructure.

Pinned by: `tests/regressions/test_issue_9807_per_backend_credit_isolation.py`

**Why:** Existing regression tests assert exact signatures; renaming breaks #9807 per-backend isolation guarantees.

---
id: 2792
topic: testing
source_issue: 11862
source_phase: plan
created_at: 2026-09-01T03:40:49.615577+00:00
status: active
corroborations: 1
---

# Pin COLLECTED_STANDARDS two-directions: every id decided, no decision for uncollected

When adding a standard id to `COLLECTED_STANDARDS` in `src/policy/facts.py`, extend the engine test in `tests/test_policy_python_engine.py` to assert both directions: every id in `COLLECTED_STANDARDS` reaches a decision, and the engine judges no standard that nothing collects for.

Example: `STANDARD_CHARTER = "charter"` added alongside `STANDARD_PYRAMID`; `STANDARD_PURPOSE` from #11856 shares the same namespace, so whoever lands second rebases.

**Why:** A one-direction pin lets a stale id linger in `COLLECTED_STANDARDS` with no engine arm, or an engine arm collect for an unregistered id — both silently break the policy seam.

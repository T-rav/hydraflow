---
id: 2688
topic: testing
source_issue: 11314
source_phase: plan
created_at: 2026-08-16T07:29:20.234641+00:00
status: active
corroborations: 1
---

# Assert sentinels against Pydantic Field constraints dynamically

When introducing a sentinel value meant to bypass an upper bound, assert it against the actual Pydantic config constraint. For `UNKNOWN_COMPLEXITY` in `src/plan_phase.py`, add a test reading `HydraFlowConfig.model_fields[...].metadata` to assert `UNKNOWN_COMPLEXITY > le`.

**Why:** If the config's `le` constraint is bumped in the future, a static test will silently pass while the collision re-opens. A dynamic guard turns it into a red test, preventing a silent escape.

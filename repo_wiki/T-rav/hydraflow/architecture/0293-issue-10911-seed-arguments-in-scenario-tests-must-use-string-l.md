---
id: 0293
topic: architecture
source_issue: 10911
source_phase: plan
created_at: 2026-07-31T13:18:17.706655+00:00
status: active
corroborations: 1
---

# Seed arguments in scenario tests must use string literals

Use string literals, not module constants, for test seed arguments like `workflow=` in scenario suites. Do not refactor them into shared constants.

Example:
- `workflow="RC Promotion Scenario"` (Correct)
- `workflow=RC_PROMOTION_WORKFLOW` (Fails guard)

**Why:** The `TestSeedArgumentsResolve` guard statically resolves arguments using `NAMED_CONSTANTS`; new constants cause resolution failures and break the test.

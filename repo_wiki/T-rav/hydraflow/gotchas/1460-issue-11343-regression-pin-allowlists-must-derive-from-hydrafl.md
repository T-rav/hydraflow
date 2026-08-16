---
id: 1460
topic: gotchas
source_issue: 11343
source_phase: plan
created_at: 2026-08-16T13:08:39.701168+00:00
status: active
corroborations: 1
---

# Regression pin allowlists must derive from HydraFlowConfig

Regression test allowlists — such as those in `tests/regressions/test_issue_11343.py` — must derive their reachable-branch set from `HydraFlowConfig` and `is_factory_self_maintenance`, never from hardcoded path lists.

- Counter-pins (`dependabot/*`, `agent/auto-agent-*`, `agent/diag-*`, `rc/*`) stay green with no edit when derived correctly
- Weakening or hardcoding the allowlist defeats the pin's purpose

**Why:** Hardcoded allowlists silently rot when config or factory-self-maintenance logic changes; derived ones fail loudly, forcing the test to track reality.

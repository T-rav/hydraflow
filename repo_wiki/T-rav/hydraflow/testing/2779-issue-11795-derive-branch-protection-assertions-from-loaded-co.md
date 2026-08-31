---
id: 2779
topic: testing
source_issue: 11795
source_phase: plan
created_at: 2026-08-30T07:41:57.361373+00:00
status: active
corroborations: 1
---

# Derive branch protection assertions from loaded contract

Derive expected branch protection context counts from the loaded `gates.toml` instead of hardcoding literals. Use `tests/regressions/test_issue_11795.py` to assert resolver output matches the loaded contract. Avoid pinning specific counts (e.g., 14 or 5 contexts) in `test_gates_*.py`.

**Why:** Hardcoded literals break on valid contract updates if the tests aren't triggered to run.

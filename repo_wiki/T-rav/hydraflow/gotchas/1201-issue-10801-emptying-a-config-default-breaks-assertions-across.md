---
id: 1201
topic: gotchas
source_issue: 10801
source_phase: plan
created_at: 2026-07-28T10:16:18.732728+00:00
status: active
corroborations: 1
---

# Emptying a config default breaks assertions across multiple test files

Rule: When changing a config default that tests assert against (e.g. `worker_stall_tight_loops` from `["staging_bisect", "flake_tracker"]` to `[]`), update all dependent test files in the same change.

- `tests/regressions/test_issue_10241.py`, `tests/regressions/test_issue_10795.py`, and `tests/test_health_monitor_worker_stall.py` all assert the old default
- Audit `tests/regressions/` and `tests/test_*.py` for hardcoded expectations of the changed field

**Why:** Updating only one file causes CI to fail late with confusing assertion mismatches in seemingly unrelated tests, masking the real cause.

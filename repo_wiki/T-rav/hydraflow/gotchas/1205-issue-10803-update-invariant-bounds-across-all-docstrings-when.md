---
id: 1205
topic: gotchas
source_issue: 10803
source_phase: plan
created_at: 2026-07-28T10:46:37.886219+00:00
status: active
corroborations: 1
---

# Update invariant bounds across all docstrings when changing config limits

When a mathematical invariant depends on a config field bound, grep all modules and tests for stale justifications.

- The strict-inequality invariant in `HealthMonitorLoop` was incorrectly justified by `ge=1` in docstrings across `src/health_monitor_loop.py` and `tests/regressions/test_issue_10241.py`.
- Update all citations to match the new floor (`ge=2`).

**Why:** Stale prose causes future maintainers to re-derive the wrong floor and accidentally reintroduce the bug.

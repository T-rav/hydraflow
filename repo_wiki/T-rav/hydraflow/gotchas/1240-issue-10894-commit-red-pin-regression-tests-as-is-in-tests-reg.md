---
id: 1240
topic: gotchas
source_issue: 10894
source_phase: plan
created_at: 2026-07-31T11:12:50.925699+00:00
status: active
corroborations: 1
---

# Commit red-pin regression tests as-is in tests/regressions/

Regression tests like `tests/regressions/test_issue_10894.py` are authored as red pins during planning and committed unmodified. Do not adjust assertions to make them pass early.

**Why:** The red pin locks the exact failure shape; softening it to green before implementation lands defeats the purpose of catching regressions in the target behavior.

---
id: 2391
topic: testing
source_issue: 11113
source_phase: plan
created_at: 2026-08-14T09:30:40.586343+00:00
status: superseded
corroborations: 1
superseded_by: 2579
---

# Rewrite invalidated regression assertions, never delete them

When a fix invalidates an assertion in an existing regression pin (e.g. `test_ui_stage_uses_ci_entry_point`, `test_ui_stage_degrades_loudly_but_green_without_node` in `tests/regressions/test_issue_9875_quality_ui_vitest.py`), rewrite the assertion against the new shape — do not delete the test function.

**Why:** Deletion silently drops the CI-parity and node-less-green guarantees the original pin encodes; rewriting preserves them against the new implementation.

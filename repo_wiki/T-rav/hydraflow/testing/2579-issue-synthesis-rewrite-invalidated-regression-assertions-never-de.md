---
id: 2579
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.752349+00:00
status: active
corroborations: 1
supersedes: 2391
---

# Rewrite invalidated regression assertions, never delete them

When a fix invalidates an assertion in an existing regression pin (e.g. `test_ui_stage_uses_ci_entry_point` in `tests/regressions/test_issue_9875_quality_ui_vitest.py`), rewrite the assertion against the new shape — do not delete the test function.

**Why:** Deletion silently drops the CI-parity and node-less-green guarantees the original pin encodes; rewriting preserves them against the new implementation.

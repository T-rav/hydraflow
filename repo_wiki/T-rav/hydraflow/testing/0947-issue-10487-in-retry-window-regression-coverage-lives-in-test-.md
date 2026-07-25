---
id: 0947
topic: testing
source_issue: 10487
source_phase: plan
created_at: 2026-07-24T22:26:43.556503+00:00
status: superseded
corroborations: 1
superseded_by: 0953
---

# `_in_retry_window()` regression coverage lives in test_issue_10459.py

Production behavior for `_in_retry_window()` in `src/workspace_gc_loop.py` is already covered by `tests/regressions/test_issue_10459.py`; when a browser/scenario test fails against this function, treat it as test-side drift and fix the mock, not the production code or add new unit tests. If a fix here seems to require touching `src/`, that's a signal the scope has grown beyond test drift and needs re-scoping.
**Why:** keeps regression coverage centralized in one place instead of duplicating retry-window assertions across scenario layers.

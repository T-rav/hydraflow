---
id: 1512
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.803967+00:00
status: active
corroborations: 1
supersedes: 1424
---

# _in_retry_window() regression coverage in test_issue_10459.py

Production behavior for `_in_retry_window()` in `src/workspace_gc_loop.py` is already covered by `tests/regressions/test_issue_10459.py`; when a browser/scenario test fails against this function, treat it as test-side drift and fix the mock, not the production code.

Example: if a fix here seems to require touching `src/`, that's a signal the scope has grown beyond test drift and needs re-scoping.

**Why:** Keeps regression coverage centralized in one place instead of duplicating retry-window assertions across scenario layers.

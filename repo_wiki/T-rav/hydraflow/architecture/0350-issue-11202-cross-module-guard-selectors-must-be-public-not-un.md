---
id: 0350
topic: architecture
source_issue: 11202
source_phase: plan
created_at: 2026-08-15T03:13:32.213260+00:00
status: active
corroborations: 1
---

# Cross-module guard selectors must be public, not underscore-prefixed

When a regression pin imports a selector function from an architecture guard module, the selector must be public — no underscore prefix.

`tests/regressions/test_issue_11202.py` imports `active_test_files` from `tests/architecture/test_no_ignored_active_tests.py` cross-module. The pin's `getattr` fallback tolerates both `active_test_files` and `_active_test_files`, but the underscore form violates the repo's public-API naming rule.

**Why:** Cross-module imports of private names create hidden coupling that breaks when the guard author renames or removes the 'private' helper.

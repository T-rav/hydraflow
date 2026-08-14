---
id: 2411
topic: testing
source_issue: 11138
source_phase: plan
created_at: 2026-08-14T14:08:04.915423+00:00
status: superseded
corroborations: 1
superseded_by: 2592
---

# Tighten TestRegressionHits from substring to exact-equality tuples

In `tests/test_escape_auto_diagnose.py`, `TestRegressionHits` used `any("test_bug_123.py" in h …)` substring matches that passed even with the `HEAD:` prefix still attached. Assert exact equality on the full repo-relative path tuple instead.

- `assert ("tests/regressions/test_bug_123.py",) == hits`
- Add a non-ASCII filename case to catch `core.quotepath` regressions.

**Why:** Substring matches silently pass when the bug is a prefix that doesn't break the substring; only exact equality catches `HEAD:` leakage through the adapter.

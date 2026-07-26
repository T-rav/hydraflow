---
id: 1046
topic: gotchas
source_issue: 10581
source_phase: plan
created_at: 2026-07-26T01:56:36.497450+00:00
status: active
corroborations: 1
---

# Regression test docstrings can pre-authorize retargeting to a new function

`tests/regressions/test_issue_10581.py`'s docstring sanctions retargeting its `_scan` helper from `detect_drift` to the new `detect_prose_drift`, letting the RED regression test evolve alongside the fix instead of being replaced outright — its self-skipping live-entry cases (real entries from the issue) are kept intact.

**Why:** preserves the original bug's regression coverage (issue's real wiki entries) while the underlying detection mechanism changes.

---
id: 1284
topic: gotchas
source_issue: 11111
source_phase: plan
created_at: 2026-08-14T09:08:28.015694+00:00
status: active
corroborations: 1
---

# Regression acceptance pins are committed red and must go green untouched

Regression tests in `tests/regressions/test_issue_XXXXX.py` are written first (red), committed as-is, and must pass without modification once the fix lands.

- `tests/regressions/test_issue_11111.py` had 4 failures pre-fix; acceptance criterion was "must go green untouched"
- Existing unit tests (e.g. `tests/test_escape_auto_diagnose.py:251`) are re-pinned to corrected behavior, not deleted

**Why:** Treating the regression pin as immutable ensures the fix addresses the recorded failures rather than weakening the test to match the implementation.

---
id: 2641
topic: testing
source_issue: 11229
source_phase: plan
created_at: 2026-08-15T07:12:37.006301+00:00
status: active
corroborations: 1
---

# Regression pins for cap defects must be positional, not numeric

When pinning a cap/budget defect, assert the positional invariant — overflow past the cap is deferred — not that a specific numeric cap value resolves the issue.

- `tests/regressions/test_issue_11229.py`: asserts an escape ranked past `escape_ledger_max_diagnoses_per_tick` files no GitHub issue, regardless of the cap's numeric value.

**Why:** Raising the cap re-files the same defect class at a larger constant; a numeric pin would pass after a non-fix.

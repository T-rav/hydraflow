---
id: 1572
topic: gotchas
source_issue: 12059
source_phase: plan
created_at: 2026-09-02T22:09:40.835296+00:00
status: active
corroborations: 1
---

# Regression rot verification requires runtime classification, not static scanning

Distinguish live bugs from test-side drift by running actual test execution, not static scanning alone. Example: `#6408`'s `ValueError("boom")` probe is now deliberately re-raised by `reraise_on_credit_or_bug` (fix in `816ee980c`); `src/regression_rot_scan.py` cannot detect this behavioral change. Create `scripts/classify_regression_rot.py` to execute each pin and report FIXED vs RED. Why: Reopening test-drift issues as bugs dispatches implementers at non-bugs; only runtime execution reveals whether a pin is still RED or now FIXED.

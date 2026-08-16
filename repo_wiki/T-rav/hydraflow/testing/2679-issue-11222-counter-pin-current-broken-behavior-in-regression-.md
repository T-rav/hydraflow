---
id: 2679
topic: testing
source_issue: 11222
source_phase: plan
created_at: 2026-08-16T05:46:03.675045+00:00
status: active
corroborations: 1
---

# Counter-pin current broken behavior in regression tests

In `tests/regressions/test_issue_*.py`, pair each acceptance pin with counter-pins that characterize pre-fix behavior. For #11222: one pin sets `HYDRAFLOW_AUDIT_PR_BASE=main` and asserts the violation is caught (proves the fixture isn't vacuous); another leaves env unset and asserts the violation is missed (proves a reorder of `_BASE_BRANCH_CANDIDATES` alone won't fix it). The unset counter-pin must stay green before and after the fix. **Why:** without counter-pins, a superficial fix passes the acceptance pin while the root cause persists.

---
id: 0170
topic: architecture
source_issue: 10411
source_phase: plan
created_at: 2026-07-24T05:57:06.014401+00:00
status: active
corroborations: 1
---

# `_SHARED_INFRA_MODULES` name is a regression-test contract — don't rename during refactors

`tests/regressions/test_issue_10411.py` imports `_SHARED_INFRA_MODULES` from `src/adr_drift.py` by name, so systemic refactors (e.g. replacing the hardcoded list with fan-out derivation) must keep that symbol name even as its membership becomes runtime-derived. **Why:** a rename would silently break the regression test's ability to catch reintroduced ADR-drift false positives on shared-infra files like `review_advisor.py` and `review_phase/_phase.py`.

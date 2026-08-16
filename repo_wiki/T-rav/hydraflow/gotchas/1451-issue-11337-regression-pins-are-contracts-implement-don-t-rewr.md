---
id: 1451
topic: gotchas
source_issue: 11337
source_phase: plan
created_at: 2026-08-16T11:25:49.892531+00:00
status: active
corroborations: 1
---

# Regression pins are contracts — implement, don't rewrite

RED pins in `tests/regressions/test_issue_*.py` ship before implementation and define the contract. They observe consumer APIs (e.g. `fetch_reviewable_prs`, `list_open_prs`, `find_open_resolving_pr`), so superficial implementations like "accept the kwarg and drop it" cannot pass.

Implement against the pin; do not edit it. If a mid-test state transition is load-bearing to a pin's intent, leave it and document the reason in the PR body.

**Why:** Rewriting the pin to match your implementation defeats the red-green safety net and hides missing behavior.

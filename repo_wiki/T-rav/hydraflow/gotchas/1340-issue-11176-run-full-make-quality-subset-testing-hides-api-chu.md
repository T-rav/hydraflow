---
id: 1340
topic: gotchas
source_issue: 11176
source_phase: plan
created_at: 2026-08-14T22:35:54.596978+00:00
status: active
corroborations: 1
---

# Run full make quality — subset testing hides API churn across regression pins

Rule: Always run `make quality`, never file-targeted subsets, when splitting public APIs in `escape_ledger_loop.py`.

- Splitting `select_findings_to_surface` touches 7 call sites across `test_issue_10503`, `test_issue_11163`, `test_escape_dismissal_quiescence_11111`.
- A targeted run looks green while the full suite fails — the PR #8460 shape.

**Why:** Regression pins are cross-cutting; subset runs miss call-site breakage that only surfaces in the full suite.

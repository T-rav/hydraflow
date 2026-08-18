---
id: 1514
topic: gotchas
source_issue: 11458
source_phase: plan
created_at: 2026-08-18T12:25:44.377234+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Treat tests/regressions/test_issue_*.py as immutable contracts

Files under `tests/regressions/test_issue_*.py` encode acceptance contracts (owner existence, delegation, agreement, AST sweeps, liveness counter-pins). Never modify them to make a test pass — change `src/` instead. In #11458 the instruction was explicit: "Do not modify that file — it is the contract."

**Why:** Editing the regression test weakens or removes the very invariant the issue was filed to enforce, making the test tautological.

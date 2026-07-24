---
id: 0588
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.259456+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Pure error-string classification bugs need only unit + regression tests

For issue #10413 (fixing `PRManager.submit_review` self-review error classification), the plan deliberately scoped to unit tests (`tests/test_pr_manager_core.py`) + a regression test (`tests/regressions/test_issue_10413.py`), explicitly omitting a MockWorld scenario because there's no loop/orchestrator/subprocess-surface change — just string matching inside one method.

**Why:** Per `docs/standards/testing/README.md`'s three-layer pyramid, MockWorld scenarios exist to catch loop integration bugs; skip that layer when the change is contained to a single method's internal logic with no cross-phase effect.

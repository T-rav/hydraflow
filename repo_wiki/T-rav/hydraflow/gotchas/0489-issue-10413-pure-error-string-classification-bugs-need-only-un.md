---
id: 0489
topic: gotchas
source_issue: 10413
source_phase: plan
created_at: 2026-07-24T06:07:17.313502+00:00
status: superseded
corroborations: 1
superseded_by: 0494
---

# Pure error-string classification bugs need only unit + regression tests

For issue #10413 (fixing `PRManager.submit_review` self-review error classification), the plan deliberately scoped to unit tests (`tests/test_pr_manager_core.py`) + a regression test (`tests/regressions/test_issue_10413.py`), explicitly omitting a MockWorld scenario because there's no loop/orchestrator/subprocess-surface change — just string matching inside one method.

**Why:** per `docs/standards/testing/README.md`'s three-layer pyramid, MockWorld scenarios exist to catch loop *integration* bugs; skip that layer when the change is contained to a single method's internal logic with no cross-phase effect.

---
id: 0746
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.885376+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0763
---

# Pure error-string classification bugs need only unit + regression tests

For issue #10413 (fixing `PRManager.submit_review` self-review error classification), the plan deliberately scoped to unit tests (`tests/test_pr_manager_core.py`) + a regression test (`tests/regressions/test_issue_10413.py`), explicitly omitting a MockWorld scenario because there's no loop/orchestrator/subprocess-surface change — just string matching inside one method.

**Why:** Per `docs/standards/testing/README.md`'s three-layer pyramid, MockWorld scenarios exist to catch loop integration bugs; skip that layer when the change is contained to a single method's internal logic with no cross-phase effect.

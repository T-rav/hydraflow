---
id: 0756
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.919721+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Scope-guard tactical allowlist PRs to the exact diff to avoid parent-issue stall

When splitting a tactical fix off a stalled/broader parent issue (here, #10455 sliced from #10411's validated commit 92c9a12c), enforce the diff at review to just the two string literals plus a lineage comment in `src/adr_drift.py` and the new test file — widening into `_citation_drifts`, config, or the resolver loop reintroduces the complexity that stalled the parent.

**Why:** Scope creep back into the resolver is the exact failure mode the tactical split was meant to avoid.

---
id: 0755
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.917442+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0763
---

# Untracked near-duplicate regression drafts trip jscpd — land only the matching one

When two near-identical local drafts exist for overlapping issues (e.g. `test_issue_10411.py` and `test_issue_10455.py` both testing `_SHARED_INFRA_MODULES` behavior), commit only the one matching the current issue's number and the `test_issue_NNNNN.py` convention.

**Why:** shipping both duplicate files trips `make quality`'s jscpd duplication check, turning a clean tactical slice into a CI failure.

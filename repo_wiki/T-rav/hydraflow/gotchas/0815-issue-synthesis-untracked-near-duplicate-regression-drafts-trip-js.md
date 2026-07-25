---
id: 0815
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:04.016512+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Untracked near-duplicate regression drafts trip jscpd — land only the matching one

When two near-identical local drafts exist for overlapping issues (e.g. `test_issue_10411.py` and `test_issue_10455.py` both testing `_SHARED_INFRA_MODULES` behavior), commit only the one matching the current issue's number and the `test_issue_NNNNN.py` convention.

**Why:** shipping both duplicate files trips `make quality`'s jscpd duplication check, turning a clean tactical slice into a CI failure.

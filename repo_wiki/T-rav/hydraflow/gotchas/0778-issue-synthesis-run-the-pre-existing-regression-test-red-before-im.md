---
id: 0778
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:03.973849+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Run the pre-existing regression test red before implementing its fix

Confirm a pre-written regression test fails before implementing its fix, then make it pass — don't write the test after the fact.

Example: `tests/regressions/test_issue_10290.py` was authored before the fix for issue #10290 and had to reproduce the bug (infra parks sharing the 24h clarification floor) when run red; the plan also permits extending the regression's signal probe if it doesn't yet observe the new park-class/comment-marker surface.

**Why:** Confirms the regression test actually reproduces the bug rather than passing vacuously before and after the change.

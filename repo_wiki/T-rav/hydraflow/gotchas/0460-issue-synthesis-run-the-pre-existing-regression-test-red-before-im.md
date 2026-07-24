---
id: 0460
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.388390+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Run the pre-existing regression test red before implementing its fix

Confirm a pre-written regression test fails before implementing its fix, then make it pass — don't write the test after the fact.

Example: `tests/regressions/test_issue_10290.py` was authored before the fix for issue #10290 and had to reproduce the bug (infra parks sharing the 24h clarification floor) when run red; the plan also permits extending the regression's signal probe if it doesn't yet observe the new park-class/comment-marker surface.

**Why:** Confirms the regression test actually reproduces the bug rather than passing vacuously before and after the change.

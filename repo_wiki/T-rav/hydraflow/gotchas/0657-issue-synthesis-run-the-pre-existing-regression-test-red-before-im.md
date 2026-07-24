---
id: 0657
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.445490+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Run the pre-existing regression test red before implementing its fix

Confirm a pre-written regression test fails before implementing its fix, then make it pass — don't write the test after the fact.

Example: `tests/regressions/test_issue_10290.py` was authored before the fix for issue #10290 and had to reproduce the bug (infra parks sharing the 24h clarification floor) when run red; the plan also permits extending the regression's signal probe if it doesn't yet observe the new park-class/comment-marker surface.

**Why:** Confirms the regression test actually reproduces the bug rather than passing vacuously before and after the change.

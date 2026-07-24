---
id: 0416
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.291748+00:00
status: superseded
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0446
---

# Run the pre-existing regression test red before implementing its fix

Confirm a pre-written regression test fails before implementing its fix, then make it pass — don't write the test after the fact.

Example: `tests/regressions/test_issue_10290.py` was authored before the fix for issue #10290 and had to reproduce the bug (infra parks sharing the 24h clarification floor) when run red; the plan also permits extending the regression's signal probe if it doesn't yet observe the new park-class/comment-marker surface.

**Why:** Confirms the regression test actually reproduces the bug rather than passing vacuously before and after the change.

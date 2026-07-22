---
id: 0362
topic: gotchas
source_issue: 10290
source_phase: plan
created_at: 2026-07-22T17:18:40.189901+00:00
status: active
corroborations: 1
---

# Run the pre-existing regression test red before implementing its fix

For issue #10290, `tests/regressions/test_issue_10290.py` was written before the fix and must be confirmed failing first, then turned green by the implementation — not written after the fact. The plan also permits extending the regression's signal probe (per its own docstring) if it doesn't yet observe the new park-class/comment-marker surface.

**Why:** confirms the regression test actually reproduces the bug (infra parks sharing the 24h clarification floor) rather than passing vacuously before and after the change.

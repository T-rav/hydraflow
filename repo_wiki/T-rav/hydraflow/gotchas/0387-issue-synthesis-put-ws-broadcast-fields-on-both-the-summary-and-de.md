---
id: 0387
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.392493+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Put WS-broadcast fields on both the summary and detail model, not detail-only

If a field is only added to a detail-only model (e.g. `EpicDetail`), but the live update path (`epic_update` reducer) replaces panel state with the summary model (`EpicProgress`), the field will flap to its default on every WS push.

Example: for issue #10299's `execution` field on `src/models.py`, it had to be added to BOTH `EpicProgress` and `EpicDetail` for this reason.

**Why:** Reducers that swap in a narrower payload silently erase fields the wider payload had, causing UI flicker that's hard to reproduce outside a live WS session.

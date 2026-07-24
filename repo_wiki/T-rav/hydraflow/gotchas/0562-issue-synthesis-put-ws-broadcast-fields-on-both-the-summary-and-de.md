---
id: 0562
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.190748+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Put WS-broadcast fields on both the summary and detail model, not detail-only

If a field is only added to a detail-only model (e.g. `EpicDetail`), but the live update path (`epic_update` reducer) replaces panel state with the summary model (`EpicProgress`), the field will flap to its default on every WS push.

Example: for issue #10299's `execution` field on `src/models.py`, it had to be added to BOTH `EpicProgress` and `EpicDetail` for this reason.

**Why:** Reducers that swap in a narrower payload silently erase fields the wider payload had, causing UI flicker that's hard to reproduce outside a live WS session.

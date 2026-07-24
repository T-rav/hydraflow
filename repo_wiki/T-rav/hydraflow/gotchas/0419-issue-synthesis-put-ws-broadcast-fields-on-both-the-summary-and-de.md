---
id: 0419
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.293638+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Put WS-broadcast fields on both the summary and detail model, not detail-only

If a field is only added to a detail-only model (e.g. `EpicDetail`), but the live update path (`epic_update` reducer) replaces panel state with the summary model (`EpicProgress`), the field will flap to its default on every WS push.

Example: for issue #10299's `execution` field on `src/models.py`, it had to be added to BOTH `EpicProgress` and `EpicDetail` for this reason.

**Why:** Reducers that swap in a narrower payload silently erase fields the wider payload had, causing UI flicker that's hard to reproduce outside a live WS session.

---
id: 0366
topic: gotchas
source_issue: 10299
source_phase: plan
created_at: 2026-07-22T17:49:09.980167+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# Put WS-broadcast fields on both the summary and detail model, not detail-only

If a field is only added to a detail-only model (e.g. `EpicDetail`), but the live update path (`epic_update` reducer) replaces panel state with the summary model (`EpicProgress`), the field will flap to its default on every WS push. For issue #10299's `execution` field on `src/models.py`, it had to be added to BOTH `EpicProgress` and `EpicDetail` for this reason.

**Why:** reducers that swap in a narrower payload silently erase fields the wider payload had, causing UI flicker that's hard to reproduce outside a live WS session.

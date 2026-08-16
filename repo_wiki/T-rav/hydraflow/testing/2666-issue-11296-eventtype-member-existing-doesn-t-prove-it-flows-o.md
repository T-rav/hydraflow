---
id: 2666
topic: testing
source_issue: 11296
source_phase: plan
created_at: 2026-08-16T02:48:52.749353+00:00
status: active
corroborations: 1
---

# EventType member existing doesn't prove it flows on the bus

An `EventType` enum member in `src/timeline.py` is necessary but not sufficient — verify the event is actually emitted from a publish site before wiring UI segmentation to it. `EventType.PHASE_CHANGE` had one emit site (`src/server.py`, boot `idle`), yet `src/ui/src/operator/model/timeline.js` treated it as the only container boundary.

**Why:** A vocabulary entry with no producer silently degrades the UI to one boot card; the fixture layer masked this because tests fabricated `phase_change` per transition.

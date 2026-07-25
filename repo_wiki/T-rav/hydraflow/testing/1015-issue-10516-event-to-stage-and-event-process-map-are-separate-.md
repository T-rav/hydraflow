---
id: 1015
topic: testing
source_issue: 10516
source_phase: plan
created_at: 2026-07-25T05:52:44.074199+00:00
status: active
corroborations: 1
---

# EVENT_TO_STAGE and EVENT_PROCESS_MAP are separate maps — filling one doesn't fill the other

`src/ui/src/hooks/useTimeline.js:16`'s `EVENT_TO_STAGE` and `src/ui/src/constants.js:96`'s `EVENT_PROCESS_MAP` both route event types but serve different purposes (timeline stage derivation vs. processing dispatch). An event type can already be wired into `EVENT_PROCESS_MAP` while being completely absent from `EVENT_TO_STAGE` — as happened with `hitl_escalation`/`hitl_update`, which left `stages.hitl` permanently `pending`. When wiring a new event type into timeline UI, check both maps independently; presence in one is not evidence of coverage in the other.

**Why:** prevents shipping a stage that silently never activates because only the dispatch map was updated.

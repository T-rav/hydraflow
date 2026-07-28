---
id: 1202
topic: gotchas
source_issue: 10799
source_phase: plan
created_at: 2026-07-28T10:31:44.654945+00:00
status: active
corroborations: 1
---

# toTimeline holds one open container per issue, closes on stage change

Rule: In `src/ui/src/operator/model/timeline.js`, `toTimeline` walks events chronologically maintaining one open container per issue; an event whose derived stage differs from that issue's open container closes it (`endTs` = event ts) and opens a new one. Stage-less events (`transcript_line` with no `source`) join the issue's open container; per-issue `phase_change` is an authoritative boundary. **Why:** Deriving containers only from `phase_change` produces never-closing "Idle" cards or empty panels once the boot event ages out of the ring.

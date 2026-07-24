---
id: 0398
topic: gotchas
source_issue: 10314
source_phase: plan
created_at: 2026-07-22T18:34:32.045598+00:00
status: superseded
corroborations: 1
superseded_by: 0402
---

# epic_number-only keying can merge same-numbered epics across repos under repo=__all__

Merging epics by `epic_number` alone (as planned for `mergeEpics` in `HydraFlowContext.jsx`) is a pre-existing limitation, not a regression introduced by the merge fix: when the UI aggregates across repos (`repo=__all__`), two different repos' epic #N would collide and merge into one entry. Filed as a discovered issue during #10314 planning rather than fixed inline, since it's out of scope for the flicker fix.

**Why:** documents a known gap so a future fix (composite key of `repo` + `epic_number`) isn't mistaken for new breakage.

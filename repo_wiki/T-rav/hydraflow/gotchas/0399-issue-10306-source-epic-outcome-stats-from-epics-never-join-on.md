---
id: 0399
topic: gotchas
source_issue: 10306
source_phase: plan
created_at: 2026-07-24T03:48:07.536838+00:00
status: active
corroborations: 1
---

# Source epic outcome stats from epics[], never join on issueHistory.epic

Epic progress/counts must come from the authoritative `epics[]` context array (`completed`/`failed`/`total_children`/`percent_complete`), not by joining against the free-string `item.epic` field on `issueHistory` rows. The free-string join is fragile to renames/typos and can silently misattribute issues to the wrong epic.

Example: `EpicOutcomeCard` in `src/ui/src/components/OutcomeCard.jsx` reads stats directly off its `epics[]` entry; it never filters `issueHistory` by `item.epic === epic.title`.

**Why:** avoids a class of stat-drift bugs where epic dashboards show wrong child counts because the string join missed or double-matched issues.

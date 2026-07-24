---
id: 0153
topic: architecture
source_issue: 10306
source_phase: plan
created_at: 2026-07-24T03:48:07.536882+00:00
status: active
corroborations: 1
---

# Land component deletion and its ported behavior in the same PR, not sequenced

When removing a component that owns a side-effecting behavior (e.g. a lazy API fetch), the replacement must port that behavior before the deletion lands — sequencing deletion first drops the behavior even if a later PR restores it in a new home.

Example: `EpicRow`'s lazy `/api/epics/{n}` child-fetch must exist in `EpicOutcomeCard` (`OutcomeCard.jsx`) before `EpicRow` is deleted from `StreamView.jsx`; the #10306 plan calls this out as "P3 can proceed in parallel; land together."

**Why:** prevents a merged intermediate state where epic child-issue expansion silently stops working between the deletion PR and the port PR.

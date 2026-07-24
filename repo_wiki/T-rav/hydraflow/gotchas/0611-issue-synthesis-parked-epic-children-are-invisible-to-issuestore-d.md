---
id: 0611
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.229449+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Parked epic children are invisible to IssueStore — derive state from GH labels

Derive an epic's paused state from child GitHub labels directly, not from IssueStore — IssueStore's fetch excludes issues carrying `parked_label`, so parked children never appear in `_active`/`_in_flight`/queue lookups.

Example: `EpicManager._build_detail` (src/epic.py) inspects child GitHub labels directly to classify an epic as `paused` when all children are parked, then memoizes the result so the synchronous `get_progress` path can reuse it without re-fetching.

**Why:** Treating IssueStore as the sole source of truth for epic execution state silently misclassifies all-parked epics as `idle` instead of `paused`.

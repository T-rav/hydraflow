---
id: 0563
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.191546+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Parked epic children are invisible to IssueStore — derive state from GH labels

Derive an epic's paused state from child GitHub labels directly, not from IssueStore — IssueStore's fetch excludes issues carrying `parked_label`, so parked children never appear in `_active`/`_in_flight`/queue lookups.

Example: `EpicManager._build_detail` (src/epic.py) inspects child GitHub labels directly to classify an epic as `paused` when all children are parked, then memoizes the result so the synchronous `get_progress` path can reuse it without re-fetching.

**Why:** Treating IssueStore as the sole source of truth for epic execution state silently misclassifies all-parked epics as `idle` instead of `paused`.

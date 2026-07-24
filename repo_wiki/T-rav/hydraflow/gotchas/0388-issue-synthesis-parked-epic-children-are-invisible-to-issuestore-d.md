---
id: 0388
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.393447+00:00
status: active
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
---

# Parked epic children are invisible to IssueStore — derive their state from GH labels

Derive an epic's paused state from child GitHub labels directly, not from IssueStore — IssueStore's fetch excludes issues carrying `parked_label`, so parked children never appear in `_active`/`_in_flight`/queue lookups.

Example: `EpicManager._build_detail` (src/epic.py) inspects child GitHub labels directly to classify an epic as `paused` when all children are parked, then memoizes the result so the synchronous `get_progress` path can reuse it without re-fetching.

**Why:** Treating IssueStore as the sole source of truth for epic execution state silently misclassifies all-parked epics as `idle` instead of `paused`.

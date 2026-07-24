---
id: 0367
topic: gotchas
source_issue: 10299
source_phase: plan
created_at: 2026-07-22T17:49:09.980176+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# Parked epic children are invisible to IssueStore — derive their state from GH labels

IssueStore's fetch excludes issues carrying `parked_label`, so parked children never show up in `_active`/`_in_flight`/queue lookups. To classify an epic as `paused` when all children are parked, `EpicManager._build_detail` (src/epic.py) must inspect child GitHub labels directly rather than IssueStore, then memoize the result so the synchronous `get_progress` path can reuse it without re-fetching.

**Why:** treating IssueStore as the sole source of truth for epic execution state silently misclassifies all-parked epics as `idle` instead of `paused`.

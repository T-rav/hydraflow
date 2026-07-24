---
id: 0512
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.783938+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Parked epic children are invisible to IssueStore — derive state from GH labels

Derive an epic's paused state from child GitHub labels directly, not from IssueStore — IssueStore's fetch excludes issues carrying `parked_label`, so parked children never appear in `_active`/`_in_flight`/queue lookups.

Example: `EpicManager._build_detail` (src/epic.py) inspects child GitHub labels directly to classify an epic as `paused` when all children are parked, then memoizes the result so the synchronous `get_progress` path can reuse it without re-fetching.

**Why:** Treating IssueStore as the sole source of truth for epic execution state silently misclassifies all-parked epics as `idle` instead of `paused`.

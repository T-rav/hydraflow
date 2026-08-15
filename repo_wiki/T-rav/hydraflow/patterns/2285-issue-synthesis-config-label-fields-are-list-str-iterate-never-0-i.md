---
id: 2285
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T01:03:09.951759+00:00
status: superseded
corroborations: 1
supersedes: 2169
superseded_by: 2405
---

# Config label fields are list[str] — iterate, never [0]-index

Label fields on `HydraFlowConfig` (e.g. `hitl_queue_label`, `trust_loop_anomaly_label`) are `list[str]`, not scalars — iterate the full list, never `[0]`-index.

Example: `_collect_hitl_items` in `src/trust_fleet_sanity_loop.py` must iterate all labels, not just `hitl_queue_label[0]`.

**Why:** `[0]`-indexing silently drops multi-label configs and narrows the queue scan to one label, breaking the composition signal under non-default configs.

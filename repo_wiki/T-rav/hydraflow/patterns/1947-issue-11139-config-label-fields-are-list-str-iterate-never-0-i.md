---
id: 1947
topic: patterns
source_issue: 11139
source_phase: plan
created_at: 2026-08-14T14:16:51.498113+00:00
status: superseded
corroborations: 1
superseded_by: 2053
---

# Config label fields are list[str] — iterate, never [0]-index

Label fields on `HydraFlowConfig` (e.g., `hitl_queue_label`, `trust_loop_anomaly_label`) are `list[str]`, not scalar strings. When scanning HITL composition in `_collect_hitl_items` (`src/trust_fleet_sanity_loop.py`), iterate the full list rather than indexing `[0]`.

**Why:** `[0]`-indexing silently drops multi-label configs and narrows the queue scan to one label, breaking the composition signal under non-default configs.

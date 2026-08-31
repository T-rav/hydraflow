---
id: 4081
topic: patterns
source_issue: 11547
source_phase: plan
created_at: 2026-08-30T07:44:19.983871+00:00
status: active
corroborations: 1
---

# Don't move HydraFlowConfig fields — save_config_file JSON keys reorder

Keep `HydraFlowConfig` field declarations in place during method and data-table extraction PRs. Moving a field reorders `model_fields` (Pydantic 2.12.5 dict order equals declaration order), which reorders keys in `save_config_file`'s JSON output.
- Extract methods and env tables freely; leave field definitions where they are
- Field reordering belongs in a dedicated burn-down PR
**Why:** JSON key reordering is a blast radius beyond the diff — snapshots and callers break silently.

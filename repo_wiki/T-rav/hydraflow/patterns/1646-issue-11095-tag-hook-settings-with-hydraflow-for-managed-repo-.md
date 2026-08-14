---
id: 1646
topic: patterns
source_issue: 11095
source_phase: plan
created_at: 2026-08-14T08:32:23.164039+00:00
status: active
corroborations: 1
---

# Tag hook settings with _hydraflow for managed-repo propagation

Any hook entry added to `.claude/settings.json` must include `"_hydraflow": true` so `merge_assets.merge_settings_file` propagates it to managed repos.

Example: the `SubagentStop` hook entry is tagged `"_hydraflow": true` alongside its command and matcher fields.

**Why:** Without the tag, managed repos silently lose the hook and enforcement is inconsistent across the fleet.

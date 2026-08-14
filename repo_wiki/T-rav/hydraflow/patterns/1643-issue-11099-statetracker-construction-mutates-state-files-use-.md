---
id: 1643
topic: patterns
source_issue: 11099
source_phase: plan
created_at: 2026-08-14T07:08:09.480482+00:00
status: superseded
corroborations: 1
superseded_by: 1736
---

# StateTracker construction mutates state files — use StateData for reads

When you need read-only access to `state.json`, do NOT construct a `StateTracker`. Its `__init__` → `load()` → `_maybe_migrate_worker_states()` chain calls `save()`, which rewrites legacy state files. Instead, read directly:

- `json.loads(path.read_text())` → `StateData.model_validate(...)`

This applies to any diagnostic or CLI that must leave inputs byte-identical.
**Why:** Constructing StateTracker for a "read-only" command silently corrupts state files, breaking the read-only contract and potentially destabilizing the scheduler.

---
id: 1832
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.331802+00:00
status: active
corroborations: 1
supersedes: 1736
---

# StateTracker construction mutates state files — use StateData for reads

When you need read-only access to `state.json`, do NOT construct a `StateTracker`. Its `__init__` → `load()` → `_maybe_migrate_worker_states()` chain calls `save()`, which rewrites legacy state files. Instead, read directly via `json.loads(path.read_text())` → `StateData.model_validate(...)`.

Example: This applies to any diagnostic or CLI that must leave inputs byte-identical.

**Why:** Constructing StateTracker for a "read-only" command silently corrupts state files, breaking the read-only contract and potentially destabilizing the scheduler.

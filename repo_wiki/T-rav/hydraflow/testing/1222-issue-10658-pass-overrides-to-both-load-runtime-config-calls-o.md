---
id: 1222
topic: testing
source_issue: 10658
source_phase: plan
created_at: 2026-07-26T15:42:45.056049+00:00
status: superseded
corroborations: 1
superseded_by: 1296
---

# Pass overrides to both load_runtime_config calls on restore

`src/server.py`'s restore loop calls `load_runtime_config` twice — the initial load and the data-class reload. Pass merged overrides to **both** calls.

If only the first call carries overrides, a repo needing a data-class upgrade silently drops operator edits on the upgrade path.

**Why:** Happy-path tests pass with one call; the silent drop only manifests on the upgrade path, which is rarely exercised.

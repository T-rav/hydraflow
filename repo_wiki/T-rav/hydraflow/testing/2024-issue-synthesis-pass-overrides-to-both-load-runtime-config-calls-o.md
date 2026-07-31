---
id: 2024
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.709658+00:00
status: active
corroborations: 1
supersedes: 1897
---

# Pass overrides to both load_runtime_config calls on restore

src/server.py's restore loop calls load_runtime_config twice — the initial load and the data-class reload. Pass merged overrides to both calls.

Example: if only the first call carries overrides, a repo needing a data-class upgrade silently drops operator edits on the upgrade path.

**Why:** Happy-path tests pass with one call; the silent drop only manifests on the upgrade path, which is rarely exercised.

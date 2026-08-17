---
id: 3805
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:56.262815+00:00
status: superseded
corroborations: 1
supersedes: 3660
superseded_by: 3952
---

# Merge repo identity keys last over stored overrides

When rebuilding a per-repo `HydraFlowConfig` from a `RepoRecord`, merge `record.overrides` first and structural keys (`repo_root`, `repo`, `repo_data_class`) last.

Example: `merged = {**defaults, **record.overrides, "repo_root": record.path, "repo": record.slug, ...}`

**Why:** `data_root/repos.json` is hand-editable; merging identity keys last prevents a stale or hand-edited stored value from hijacking repo identity.

---
id: 0662
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:03:14.330898+00:00
status: superseded
corroborations: 1
supersedes: 0620
superseded_by: 0707
---

# Merge repo identity keys last over stored overrides

When rebuilding a per-repo `HydraFlowConfig` from a `RepoRecord`, merge `record.overrides` first and structural keys (`repo_root`, `repo`, `repo_data_class`) last.

Example: `merged = {**defaults, **record.overrides, "repo_root": record.path, "repo": record.slug, ...}`

**Why:** `data_root/repos.json` is hand-editable; merging identity keys last prevents a stale or hand-edited stored value from hijacking repo identity.

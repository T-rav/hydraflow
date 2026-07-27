---
id: 0620
topic: patterns
source_issue: 10658
source_phase: plan
created_at: 2026-07-26T15:42:45.056039+00:00
status: superseded
corroborations: 1
superseded_by: 0662
---

# Merge repo identity keys last over stored overrides

When rebuilding a per-repo `HydraFlowConfig` from a `RepoRecord`, merge `record.overrides` first and structural keys (`repo_root`, `repo`, `repo_data_class`) last.

```python
merged = {**defaults, **record.overrides,
          "repo_root": record.path, "repo": record.slug, ...}
```

**Why:** `data_root/repos.json` is hand-editable; merging identity keys last prevents a stale or hand-edited stored value from hijacking repo identity.

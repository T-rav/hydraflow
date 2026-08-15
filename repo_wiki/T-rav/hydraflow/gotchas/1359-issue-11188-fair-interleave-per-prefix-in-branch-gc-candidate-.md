---
id: 1359
topic: gotchas
source_issue: 11188
source_phase: plan
created_at: 2026-08-15T00:25:53.081705+00:00
status: active
corroborations: 1
---

# Fair interleave per prefix in branch_gc candidate inventory

When `_MAX_BRANCH_GC_PER_CYCLE` bounds a GC tick and one namespace vastly outnumbers others (e.g. ~183 `agent/issue-*` vs 1 `agent/auto-agent-*`), a naive `extend` starves smaller namespaces. Round-robin-interleave per `_BRANCH_GC_PREFIXES` entry instead.

- `src/stale_issue_loop.py` → `_branch_gc_candidate_branches`
- Prefix list: `agent/issue-*`, `fix/*`, `agent/auto-agent-*`

**Why:** Without fair interleave, the new namespace would never process in a single tick, making the feature appear broken.

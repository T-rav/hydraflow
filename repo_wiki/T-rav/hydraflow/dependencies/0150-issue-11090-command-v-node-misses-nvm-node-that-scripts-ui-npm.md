---
id: 0150
topic: dependencies
source_issue: 11090
source_phase: plan
created_at: 2026-08-14T06:25:31.261890+00:00
status: active
corroborations: 1
---

# command -v node misses nvm node that scripts/ui-npm.sh finds

The node guard uses `command -v node`, but `scripts/ui-npm.sh` has nvm/node-version selection that can resolve a node the outer shell cannot. On those machines the lane still skips green.

Known residual hole — document in `docs/wiki/gotchas.md` rather than silently leaving it.

**Why:** Two divergent node-discovery mechanisms cause the guard to under-detect runnable environments.

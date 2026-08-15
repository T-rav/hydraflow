---
id: 1382
topic: gotchas
source_issue: 11218
source_phase: plan
created_at: 2026-08-15T06:29:26.164477+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# reset --hard and clean -fd leave refs/stash untouched

`git reset --hard` and `git clean -fd` — the existing sync commands in `scripts/run-factory-isolated.sh` — do not prune `refs/stash`. A stale stash survives every boot sync and reappears in the workspace.

- After reset/clean, explicitly prune stashes past `HYDRAFLOW_FACTORY_STASH_MAX_AGE_DAYS` (default 14).
- Post-sync verification must assert no stale stash remains, not just a clean tree.

**Why:** Stash blindness is the actual bug class; reset + clean alone give a false clean signal while divergence persists in `refs/stash`.

---
id: 0387
topic: patterns
source_issue: 10408
source_phase: plan
created_at: 2026-07-24T05:56:46.873228+00:00
status: active
corroborations: 1
---

# clean -fd (not -fdx) in factory sync preserves .venv and gitignored caches

In `scripts/run-factory-isolated.sh`'s sync block, use `git clean -fd` without `-x` to remove untracked agent leftovers (e.g. stray `review_logs/`) while preserving gitignored `.venv`/runtime caches and the not-yet-copied `.env` (copied after the sync block runs).

**Why:** `-fdx` would wipe gitignored caches and force a slow full re-sync on every factory boot, defeating the purpose of the disposable-workspace reuse.

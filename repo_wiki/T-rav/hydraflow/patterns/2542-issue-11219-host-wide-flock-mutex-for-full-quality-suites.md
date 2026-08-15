---
id: 2542
topic: patterns
source_issue: 11219
source_phase: plan
created_at: 2026-08-15T06:20:11.276950+00:00
status: superseded
corroborations: 1
superseded_by: 2665
---

# Host-wide flock mutex for full quality suites

Use `fcntl.flock` in `scripts/quality_mutex.py` to serialize full quality suites across worktrees. Bind the lock to a host-global path like `$HOME/.hydraflow/locks/full-suite.lock`. Do not use per-worktree lock paths, otherwise concurrent worktrees will OOM-reap each other.

**Why:** OOM kills occur when concurrent full suites exceed the memory ceiling; a per-host lock forces serialization.

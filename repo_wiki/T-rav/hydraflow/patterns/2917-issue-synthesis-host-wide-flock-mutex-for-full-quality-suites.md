---
id: 2917
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.491137+00:00
status: superseded
corroborations: 1
supersedes: 2788
superseded_by: 3044
---

# Host-wide flock mutex for full quality suites

Use `fcntl.flock` in `scripts/quality_mutex.py` to serialize full quality suites across worktrees. Bind the lock to a host-global path like `$HOME/.hydraflow/locks/full-suite.lock`. Do not use per-worktree lock paths, otherwise concurrent worktrees will OOM-reap each other. See also: [patterns] — Prevent self-deadlock in nested quality suites.

**Why:** OOM kills occur when concurrent full suites exceed the memory ceiling; a per-host lock forces serialization.

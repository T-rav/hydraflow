---
id: 3178
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:06.252093+00:00
status: active
corroborations: 1
supersedes: 3044
---

# Host-wide flock mutex for full quality suites

Use `fcntl.flock` in `scripts/quality_mutex.py` to serialize full quality suites across worktrees. Bind the lock to a host-global path like `$HOME/.hydraflow/locks/full-suite.lock`. Do not use per-worktree lock paths, otherwise concurrent worktrees will OOM-reap each other. See also: [patterns] — Prevent self-deadlock in nested quality suites.

**Why:** OOM kills occur when concurrent full suites exceed the memory ceiling; a per-host lock forces serialization.

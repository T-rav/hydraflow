---
id: 0416
topic: architecture
source_issue: 11501
source_phase: plan
created_at: 2026-08-21T01:19:24.541871+00:00
status: active
corroborations: 1
---

# Realpath worktree paths before string comparison on macOS

Before comparing a caller-typed directory path against paths in `git worktree list --porcelain`, resolve both with `cd -P <dir> && pwd` (realpath).

- macOS git prints `/private/tmp/...` for a `/tmp/...` worktree.
- A naive string `==` compare mismatches silently, making every reuse look like a new creation.

**Why:** Path-alias divergence on macOS causes the safety check in `scripts/hf_worktree.sh` to pass when it should fail, reopening the wrong-branch hole.

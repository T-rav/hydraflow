---
id: 0415
topic: architecture
source_issue: 11501
source_phase: plan
created_at: 2026-08-21T01:19:24.541818+00:00
status: active
corroborations: 1
---

# Check worktree branch via porcelain, not cd + rev-parse

Use `git worktree list --porcelain` and parse `worktree <abspath>` / `branch refs/heads/<n>` / `detached` lines to inspect an existing worktree's branch. Never `cd` into the directory and run `git rev-parse --abbrev-ref HEAD`.

```bash
# Correct: porcelain enumeration
git worktree list --porcelain
# Bug being fixed: cd + rev-parse can report wrong branch
```

**Why:** `cd` into a stale or reused-name worktree can surface the wrong branch, which is the root cause of the 1469-file wrong-branch incident that motivated `scripts/hf_worktree.sh`.

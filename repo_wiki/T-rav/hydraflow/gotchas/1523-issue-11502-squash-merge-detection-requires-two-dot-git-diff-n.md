---
id: 1523
topic: gotchas
source_issue: 11502
source_phase: plan
created_at: 2026-08-21T01:24:51.844484+00:00
status: active
corroborations: 1
---

# Squash-merge detection requires two-dot git diff, not three-dot

Use `git diff --name-only origin/<base> HEAD` (two-dot) to detect that a branch's content has landed on base. The three-dot form `origin/<base>...HEAD` is NON-empty after a squash merge because it compares against the merge-base, not the base tip. Empirically verified with a 4-commit squash into `staging`.

**Why:** Following the issue's three-dot suggestion verbatim means the landed check in `WorkspaceGCLoop` never returns true and dead worktrees keep accumulating in `.claude/worktrees/`.

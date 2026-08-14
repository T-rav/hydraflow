---
id: 1263
topic: gotchas
source_issue: 11087
source_phase: plan
created_at: 2026-08-14T06:12:02.565871+00:00
status: active
corroborations: 1
---

# Exempt factory agent worktree paths from session PR hooks

Hooks that arm on `gh pr create` must skip payloads from factory agent worktrees — paths matching `/worktrees/<slug>/issue-<N>/`. Pipeline PRs already pass through `src/review_phase/_phase.py`, so arming a session marker for them is redundant and would double-gate. **Why:** Without the exemption, every pipeline PR triggers a Stop-block that the pipeline cannot resolve, stalling automated flows.

---
id: 1296
topic: gotchas
source_issue: 11125
source_phase: plan
created_at: 2026-08-14T11:39:37.484096+00:00
status: active
corroborations: 1
---

# hf.auto-lint-after-edit.sh temp paths must avoid /worktrees/ shape

`hf.auto-lint-after-edit.sh` switches to detection-only mode when the active file path matches `/worktrees/<slug>/issue-<N>/`, emitting no `LINT-STRIP` warning.

- Tests exercising the hook's mutation branch must keep temp files outside that path shape (e.g. `/tmp/hydraflow_hook_test_*`).
- A temp file under a worktree-shaped path silently disables the warning, making the test flaky.

**Why:** The path guard is a feature for real worktrees, but it makes the hook test fail intermittently in CI if the temp file accidentally matches the pattern.

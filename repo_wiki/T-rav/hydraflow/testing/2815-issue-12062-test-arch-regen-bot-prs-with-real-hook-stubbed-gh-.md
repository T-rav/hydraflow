---
id: 2815
topic: testing
source_issue: 12062
source_phase: plan
created_at: 2026-09-02T22:21:22.693597+00:00
status: active
corroborations: 1
---

# Test arch-regen bot PRs with real hook, stubbed gh, both async entry points

Regression tests use real scratch git repos with actual pre-commit hook; only gh token faked. Test both `generate_and_open_pr_async` and `open_automated_pr_async` to pin class at both seams. Both share `_finalize_pr_from_worktree` tail. Hook is external to codebase; only real fs/git tests catch it.

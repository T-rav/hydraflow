---
id: 2660
topic: testing
source_issue: 11284
source_phase: plan
created_at: 2026-08-16T01:29:44.315661+00:00
status: active
corroborations: 1
---

# Git-dependent regression tests must shell to real git in temp repos, not mock _run_git

Regression tests for git-flow logic (e.g. `tests/regressions/`) must use real git in temp repos with a local `origin` remote. Commands like `git rev-list --count origin/<base>..<branch>` require an actual `origin/<base>` ref that mocks cannot faithfully reproduce. Set up: temp repo, `git init --bare` origin, `git remote add origin <path>`, push base ref.

**Why:** Mocked `_run_git` calls produce brittle tests that pass against incorrect assumptions about ref availability and rev-list semantics.

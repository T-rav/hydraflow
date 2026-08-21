---
id: 1524
topic: gotchas
source_issue: 11502
source_phase: plan
created_at: 2026-08-21T01:24:51.844586+00:00
status: active
corroborations: 1
---

# Git regression tests must shell out to real git, not stub run_subprocess

Regression tests for git behavior (e.g. `tests/regressions/test_issue_11502.py`) must build real temp repos with a real `git` binary in `tmp_path`, per the git-regression convention in this repo.

- Stubbing `run_subprocess` causes the test to go GREEN against an implementation that still cannot see a squash merge.
- The squash-merge / rev-list-count distinction does not reproduce against a stubbed rev-list count.

**Why:** Stubbing the git layer hides real git-semantics bugs that only surface against the actual binary.

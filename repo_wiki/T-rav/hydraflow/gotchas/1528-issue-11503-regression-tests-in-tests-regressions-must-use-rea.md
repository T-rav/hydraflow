---
id: 1528
topic: gotchas
source_issue: 11503
source_phase: plan
created_at: 2026-08-21T02:03:56.958134+00:00
status: active
corroborations: 1
---

# Regression tests in tests/regressions/ must use real git, not stubs

Rule: Tests under `tests/regressions/` reproducing git-specific behavior must use real git in temp repos. Do not stub `rev-list`, `diff`, or `run_subprocess_result` in this directory.

Example: `tests/regressions/test_issue_11503.py` confirms a closed issue's clean worktree with unmerged commits is NOT reaped — the reproduction only triggers against real subprocess behavior, and must fail RED against pre-change code.

**Why:** Stubbed subprocesses hide git-version-specific diff/exit-code semantics; a regression that passes against a stub can pass against the buggy pre-change code and provides no real guard.

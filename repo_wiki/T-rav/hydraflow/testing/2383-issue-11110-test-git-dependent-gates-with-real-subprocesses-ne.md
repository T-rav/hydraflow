---
id: 2383
topic: testing
source_issue: 11110
source_phase: plan
created_at: 2026-08-14T08:05:02.917622+00:00
status: superseded
corroborations: 1
superseded_by: 2571
---

# Test git-dependent gates with real subprocesses, never mock

Regression tests for git-history logic in `tests/regressions/` must build real temp repos with real `git` subprocesses — never mock `subprocess.run`. Neutralize ambient state with `core.hooksPath=` and `commit.gpgsign=false` for deterministic cross-environment behavior.

In `tests/test_console_conformance.py`, keep `test_repo_ledger_is_conformant` at `check_git=False` because the `test` CI job clones shallow; the `arch` job exercises `check_git=True`.

**Why:** Mocking `subprocess.run` hides pathspec and ref-resolution bugs that only surface against real git behavior.

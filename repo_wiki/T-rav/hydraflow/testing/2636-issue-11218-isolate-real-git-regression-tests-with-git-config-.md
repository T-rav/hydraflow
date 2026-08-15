---
id: 2636
topic: testing
source_issue: 11218
source_phase: plan
created_at: 2026-08-15T06:29:26.164555+00:00
status: active
corroborations: 1
---

# Isolate real-git regression tests with GIT_CONFIG_GLOBAL=/dev/null

End-to-end regression tests for `scripts/run-factory-isolated.sh` should drive the real launcher against a throwaway origin and deliberately diverged clone, with `GIT_CONFIG_GLOBAL=/dev/null` and a stubbed `make` on `PATH`. Follow the pattern in `tests/regressions/test_factory_isolated_stale_boot_10408.py`.

- Assert only observable end state: `git stash list`, HEAD SHA, `git status --porcelain`, stdout/stderr, exit code.
- Never assert a replayed command sequence.
- Add a liveness guard: assert a stub `make run` marker file appears on the happy path so a launcher that dies early can't pass by vacuum.

**Why:** Command-sequence assertions are brittle and miss real divergence classes; observable-state assertions with isolation catch actual regressions.

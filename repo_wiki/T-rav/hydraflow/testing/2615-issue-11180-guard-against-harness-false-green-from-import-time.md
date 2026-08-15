---
id: 2615
topic: testing
source_issue: 11180
source_phase: plan
created_at: 2026-08-14T23:23:17.598899+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Guard against harness false-green from import-time failures

When loading a test module by path in a meta-regression harness, assert the module loads successfully and declares ≥1 zero-arg `test_*` function before running checks.

- `_run_zero_arg_tests` skips parametrized tests (they require fixtures), so a module whose import raises `FileNotFoundError` would look "clean" with zero tests run.
- Assert `hasattr(module, name)` and callable count ≥ 1 before proceeding.

**Why:** Without this guard, a broken import in the copied module silently produces a passing test run — the harness reports "no errors" because it ran zero tests, not because the pin self-retired.

---
id: 2813
topic: testing
source_issue: 12056
source_phase: plan
created_at: 2026-09-02T21:56:47.139370+00:00
status: active
corroborations: 1
---

# Shell hooks must be hermetic with temp directories and cleanup

Hook tests use bash with `PASS` convention, auto-discovered by `test_claude_hook_shell_tests.py`. Hermetic test: create temp `HF_HOOK_MARKER_DIR`, remove after test completes. Never mock git or filesystem.

Example: `tmpdir=$(mktemp -d); HF_HOOK_MARKER_DIR=$tmpdir <hook-command>; rm -rf $tmpdir`.

**Why:** Shell hook tests run in the default test suite alongside unit tests; state leakage (persisted markers, mock side effects) causes flaky parallel failures (see test-claude-hook-shell-tests.py pattern).

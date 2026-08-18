---
id: 2758
topic: testing
source_issue: 11434
source_phase: review
created_at: 2026-08-18T09:29:47.203068+00:00
status: active
corroborations: 1
---

# Register killpg/reap tests in REAP_TESTS for xdist serial execution

Tests that use `killpg`, process-group reap, or timing-sensitive heartbeat assertions must be added to `REAP_TESTS` in `Makefile:41` and the CI `REAP` list in `.github/workflows/ci.yml:521-527`.
- `tests/regressions/test_issue_11434.py` is structurally this class of test but is currently unregistered.

**Why:** The repo's "keep in sync" convention exists because these tests race under xdist `--forked` parallel execution; unregistered tests pass today but flake silently under host-load timing.

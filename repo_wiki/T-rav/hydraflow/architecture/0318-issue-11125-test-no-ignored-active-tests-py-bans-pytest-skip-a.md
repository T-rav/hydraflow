---
id: 0318
topic: architecture
source_issue: 11125
source_phase: plan
created_at: 2026-08-14T11:39:37.484064+00:00
status: active
corroborations: 1
---

# test_no_ignored_active_tests.py bans pytest.skip and xfail

Use a plain `return` for optional-dependency paths, never `pytest.skip` or `pytest.xfail`.

- `tests/regressions/regression_issue_10057.py:63` returns early when ruff is absent instead of skipping.
- `tests/hooks/test_hook_shell_scripts.py` follows the same pattern for the ruff/uv-absent path.

**Why:** `tests/architecture/test_no_ignored_active_tests.py` enforces this repo-wide; introducing a skip or xfail breaks the architecture gate.

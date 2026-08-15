---
id: 0345
topic: architecture
source_issue: 11186
source_phase: review
created_at: 2026-08-15T02:28:30.947474+00:00
status: active
corroborations: 1
---

# test_no_ignored_active_tests.py scan misses non-test_* files

The guard at `tests/architecture/test_no_ignored_active_tests.py` only scans filenames starting with `test` or `conftest.py` for `pytest.skip(` patterns. But `pyproject.toml:175` sets `python_files = ["test_*.py", "regression_*.py"]`, so `regression_*.py` files already bypass the guard — e.g., `tests/regressions/regression_issue_6435.py:80` has an unscanned `pytest.skip(` today.

**Why:** Support modules at `tests/` root with non-`test` prefixes (e.g., `_adr_pin_support.py`) are invisible to this quality gate; a follow-up should align the guard's filename filter with `python_files`.

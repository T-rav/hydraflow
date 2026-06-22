---
id: 0022
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.315634+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use meta-tests to enforce anti-pattern absence across the test suite

Write meta-tests that scan `tests/test_*.py` for forbidden patterns (e.g., `sys.path.insert`, "Should..." docstrings, AAA comments) and fail CI if any are found.

Example: `assert not any('sys.path.insert' in line for line in test_files)` as a standalone test.

**Why:** Manual review misses anti-patterns introduced across hundreds of test files; a meta-test turns the check into a permanent CI gate.

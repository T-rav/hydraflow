---
id: 0064
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:09:01.907264+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Use meta-tests to enforce anti-pattern absence across the test suite

Write meta-tests that scan `tests/test_*.py` for forbidden patterns (e.g., `sys.path.insert`, "Should..." docstrings, AAA comments) and fail CI if any are found.

Example: `assert not any('sys.path.insert' in line for line in test_files)` as a standalone test.

**Why:** Manual review misses anti-patterns introduced across hundreds of test files; a meta-test turns the check into a permanent CI gate.

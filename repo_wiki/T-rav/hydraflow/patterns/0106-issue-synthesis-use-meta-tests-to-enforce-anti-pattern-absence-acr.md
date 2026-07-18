---
id: 0106
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:07:53.467185+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Use meta-tests to enforce anti-pattern absence across the test suite

Write meta-tests that scan `tests/test_*.py` for forbidden patterns (e.g., `sys.path.insert`, "Should..." docstrings, AAA comments) and fail CI if any are found.

Example: `assert not any('sys.path.insert' in line for line in test_files)` as a standalone test.

**Why:** Manual review misses anti-patterns introduced across hundreds of test files; a meta-test turns the check into a permanent CI gate.

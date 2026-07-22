---
id: 0316
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.871686+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Use meta-tests to enforce anti-pattern absence in the test suite

Write meta-tests that scan `tests/test_*.py` for forbidden patterns (e.g., `sys.path.insert`, "Should..." docstrings, AAA comments) and fail CI if any are found.

Example: `assert not any('sys.path.insert' in line for line in test_files)` as a standalone test.

**Why:** Manual review misses anti-patterns introduced across hundreds of test files; a meta-test turns the check into a permanent CI gate.

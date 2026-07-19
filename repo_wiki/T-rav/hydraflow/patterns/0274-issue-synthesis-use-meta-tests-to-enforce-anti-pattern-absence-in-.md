---
id: 0274
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.713159+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Use meta-tests to enforce anti-pattern absence in the test suite

Write meta-tests that scan `tests/test_*.py` for forbidden patterns (e.g., `sys.path.insert`, "Should..." docstrings, AAA comments) and fail CI if any are found.

Example: `assert not any('sys.path.insert' in line for line in test_files)` as a standalone test.

**Why:** Manual review misses anti-patterns introduced across hundreds of test files; a meta-test turns the check into a permanent CI gate.

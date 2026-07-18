---
id: 0319
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.017870+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Never import private helpers at module level in test files

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at module top level.

Example: `def test_check_prereq(): from src.makefile_scaffold import _check_prereq_deps`

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

---
id: 0397
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.742430+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Never import private helpers at module level

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at module top level.

Example: `def test_check_prereq(): from src.makefile_scaffold import _check_prereq_deps`

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

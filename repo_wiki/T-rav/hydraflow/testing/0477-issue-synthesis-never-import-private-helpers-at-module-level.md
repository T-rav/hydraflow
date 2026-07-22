---
id: 0477
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.365366+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Never import private helpers at module level

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at module top level.

Example: `def test_check_prereq(): from src.makefile_scaffold import _check_prereq_deps`

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

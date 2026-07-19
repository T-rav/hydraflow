---
id: 0358
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.501143+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Never import private helpers at module level

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at module top level.

Example: `def test_check_prereq(): from src.makefile_scaffold import _check_prereq_deps`

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

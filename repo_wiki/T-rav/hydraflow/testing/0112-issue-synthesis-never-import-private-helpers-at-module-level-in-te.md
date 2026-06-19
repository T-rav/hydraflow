---
id: 0112
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.084968+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Never import private helpers at module level in test files

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at the top of the test module.

```python
# bad — kills entire file if symbol doesn't exist
from src.makefile_scaffold import _check_prereq_deps

# good — failure scoped to the test
def test_check_prereq():
    from src.makefile_scaffold import _check_prereq_deps
```

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

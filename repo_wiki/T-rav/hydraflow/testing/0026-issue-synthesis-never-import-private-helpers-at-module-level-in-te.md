---
id: 0026
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.830512+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Never import private helpers at module level in test files

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at the top of the test module.

```python
# bad — kills entire file if symbol doesn't exist
from src.makefile_scaffold import _check_prereq_deps

# good — failure scoped to the test that needs it
def test_check_prereq():
    from src.makefile_scaffold import _check_prereq_deps
```

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all pre-existing passing tests in that module.

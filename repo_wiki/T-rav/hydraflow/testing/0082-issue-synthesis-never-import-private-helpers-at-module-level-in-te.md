---
id: 0082
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.274748+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
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

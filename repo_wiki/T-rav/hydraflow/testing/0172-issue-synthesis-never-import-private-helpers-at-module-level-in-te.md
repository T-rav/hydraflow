---
id: 0172
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.580387+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Never import private helpers at module level in test files

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at the top of the test module.

```python
# good — failure scoped to the test
def test_check_prereq():
    from src.makefile_scaffold import _check_prereq_deps
```

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all passing tests in that module.

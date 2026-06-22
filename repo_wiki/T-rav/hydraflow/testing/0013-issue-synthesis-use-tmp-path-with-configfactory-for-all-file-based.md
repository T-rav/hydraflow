---
id: 0013
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.828219+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Use tmp_path with ConfigFactory for all file-based test I/O

All tests that read or write files must use `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)` — never write to real project paths.

```python
def test_something(tmp_path):
    config = ConfigFactory.create(base_path=tmp_path)
```

**Why:** Tests writing to real project paths corrupt the working directory and produce hard-to-reproduce cross-test pollution.

---
id: 0040
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.211556+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Use tmp_path with ConfigFactory for all file-based test I/O

All tests that read or write files must use `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)` — never write to real project paths.

```python
def test_something(tmp_path):
    config = ConfigFactory.create(base_path=tmp_path)
```

**Why:** Tests writing to real project paths corrupt the working directory and produce hard-to-reproduce cross-test pollution.

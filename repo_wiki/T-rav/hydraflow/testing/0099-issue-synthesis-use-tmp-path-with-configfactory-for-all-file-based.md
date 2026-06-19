---
id: 0099
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.081431+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Use tmp_path with ConfigFactory for all file-based test I/O

All tests that read or write files must use `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)` — never write to real project paths.

```python
def test_something(tmp_path):
    config = ConfigFactory.create(base_path=tmp_path)
```

**Why:** Tests writing to real project paths corrupt the working directory and produce hard-to-reproduce cross-test pollution.

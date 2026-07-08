---
id: 0011
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408759+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Use tmp_path and factory for all file-based test I/O

All tests that read or write files must use pytest's `tmp_path` fixture with a factory:

```python
config = ConfigFactory.create(tmp_path)
```

Never write to project-relative paths in tests.

**Why:** Writing to project paths pollutes the working tree and causes cross-test interference, especially under parallel execution.

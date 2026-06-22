---
id: 0192
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.785994+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Use tmp_path with ConfigFactory for all file-based test I/O

All tests that read or write files must use `tmp_path` combined with `ConfigFactory.create(base_path=tmp_path)` — never write to real project paths.

```python
def test_something(tmp_path):
    config = ConfigFactory.create(base_path=tmp_path)
```

**Why:** Tests writing to real project paths corrupt the working directory and produce hard-to-reproduce cross-test pollution.

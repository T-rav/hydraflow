---
id: 0096
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.080713+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Test async context managers in three standard scenarios

Test async context managers with three scenarios: (1) idempotent close — calling `close()` twice is safe, (2) context manager exit triggers `close()` exactly once, (3) `__aenter__` returns `self`.

```python
async with resource as r:
    assert r is resource
```

**Why:** Missing any scenario leaves an incomplete behavioral contract, hiding bugs in external-connection or file-handle management.

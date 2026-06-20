---
id: 0010
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.827672+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Test async context managers in three standard scenarios

Test async context managers with three scenarios: (1) idempotent close — calling `close()` twice is safe, (2) context manager exit triggers `close()` exactly once, (3) `__aenter__` returns `self`.

```python
async with resource as r:
    assert r is resource
```

**Why:** Missing any scenario leaves an incomplete behavioral contract, hiding bugs in external-connection or file-handle management.

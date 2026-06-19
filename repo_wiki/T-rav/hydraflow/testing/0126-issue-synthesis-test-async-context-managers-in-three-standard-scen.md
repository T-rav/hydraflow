---
id: 0126
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.432750+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Test async context managers in three standard scenarios

Test async context managers with three scenarios: (1) idempotent close — calling `close()` twice is safe, (2) context manager exit triggers `close()` exactly once, (3) `__aenter__` returns `self`.

```python
async with resource as r:
    assert r is resource
```

**Why:** Missing any scenario leaves an incomplete behavioral contract, hiding bugs in external-connection or file-handle management.

---
id: 0156
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.575316+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Test async context managers in three standard scenarios

Test async context managers with three scenarios: (1) idempotent close — calling `close()` twice is safe, (2) context manager exit triggers `close()` exactly once, (3) `__aenter__` returns `self`.

```python
async with resource as r:
    assert r is resource
```

**Why:** Missing any scenario leaves an incomplete behavioral contract, hiding bugs in external-connection or file-handle management.

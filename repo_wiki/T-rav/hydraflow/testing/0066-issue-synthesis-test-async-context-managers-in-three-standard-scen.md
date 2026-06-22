---
id: 0066
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.270028+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Test async context managers in three standard scenarios

Test async context managers with three scenarios: (1) idempotent close — calling `close()` twice is safe, (2) context manager exit triggers `close()` exactly once, (3) `__aenter__` returns `self`.

```python
async with resource as r:
    assert r is resource
```

**Why:** Missing any scenario leaves an incomplete behavioral contract, hiding bugs in external-connection or file-handle management.

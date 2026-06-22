---
id: 0055
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.214022+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Specify exact logger name in caplog.at_level() assertions

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger="src.billing"):
    trigger_action()
assert "expected substring" in caplog.text
```

**Why:** Without the logger filter, unrelated log messages from other modules pollute captured output and produce false positives.

---
id: 0205
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.790404+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Specify exact logger name in caplog.at_level() assertions

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger='src.billing'):
    trigger_action()
assert 'expected substring' in caplog.text
```

**Why:** Without the logger filter, unrelated log messages from other modules pollute captured output and produce false positives.

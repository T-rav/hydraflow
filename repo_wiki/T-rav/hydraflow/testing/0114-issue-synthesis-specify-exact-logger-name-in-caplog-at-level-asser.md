---
id: 0114
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.085530+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Specify exact logger name in caplog.at_level() assertions

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger='src.billing'):
    trigger_action()
assert 'expected substring' in caplog.text
```

**Why:** Without the logger filter, unrelated log messages from other modules pollute captured output and produce false positives.

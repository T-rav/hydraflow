---
id: 0084
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.275317+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Specify exact logger name in caplog.at_level() assertions

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger='src.billing'):
    trigger_action()
assert 'expected substring' in caplog.text
```

**Why:** Without the logger filter, unrelated log messages from other modules pollute captured output and produce false positives.

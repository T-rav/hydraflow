---
id: 0028
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.830864+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Specify exact logger name in caplog.at_level() assertions

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger="src.billing"):
    trigger_action()
assert "expected substring" in caplog.text
```

**Why:** Without the logger filter, unrelated log messages from other modules pollute the captured output and produce false positives.

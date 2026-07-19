---
id: 0222
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:19:21.271832+00:00
status: superseded
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
superseded_by: 0256
---

# Caplog assertions must name the exact logger

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

```python
with caplog.at_level(logging.WARNING, logger='src.module.name'):
    trigger_action()
assert 'expected substring' in caplog.text
```

Assert on message substrings specific to the logged values.

**Why:** Without the logger filter, caplog captures all loggers and assertions may match unrelated log lines, producing false positives.

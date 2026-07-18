---
id: 0013
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408997+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Caplog assertions must name the exact logger

Always pass the module's logger name when capturing logs:

```python
caplog.at_level(logging.WARNING, logger="src.module.name")
```

Clear caplog before the action under test. Assert on message substrings specific to the logged values.

**Why:** Without a logger name, caplog captures all loggers and assertions may match unrelated log lines, producing false positives.

---
id: 0456
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.341271+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Caplog assertions must name the exact logger

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

Example: `with caplog.at_level(logging.WARNING, logger='src.module.name'): trigger_action()`. Assert on message substrings specific to the logged values.

**Why:** Without the logger filter, caplog captures all loggers and assertions may match unrelated log lines, producing false positives.

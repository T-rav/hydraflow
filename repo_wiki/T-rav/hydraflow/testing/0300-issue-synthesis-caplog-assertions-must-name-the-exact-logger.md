---
id: 0300
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.005052+00:00
status: superseded
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
superseded_by: 0334
---

# Caplog assertions must name the exact logger

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

Example: `with caplog.at_level(logging.WARNING, logger='src.module.name'): trigger_action()`. Assert on message substrings specific to the logged values.

**Why:** Without the logger filter, caplog captures all loggers and assertions may match unrelated log lines, producing false positives.

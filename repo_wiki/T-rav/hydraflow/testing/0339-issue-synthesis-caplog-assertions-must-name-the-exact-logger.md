---
id: 0339
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.490686+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Caplog assertions must name the exact logger

Always pass the exact logger name to `caplog.at_level()` and clear caplog before the action under test.

Example: `with caplog.at_level(logging.WARNING, logger='src.module.name'): trigger_action()`. Assert on message substrings specific to the logged values.

**Why:** Without the logger filter, caplog captures all loggers and assertions may match unrelated log lines, producing false positives.

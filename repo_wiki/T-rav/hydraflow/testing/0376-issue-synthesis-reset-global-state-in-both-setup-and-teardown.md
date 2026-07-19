---
id: 0376
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.720009+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Reset global state in both setup and teardown

Fixtures that touch shared singletons must reset them at fixture start and at teardown.

Example: Use an autouse conftest fixture to ensure `module._rate_limit_until = 0` runs before and after every test.

**Why:** Stale state from a prior test leaks into later tests, causing order-dependent flakiness invisible in isolation.

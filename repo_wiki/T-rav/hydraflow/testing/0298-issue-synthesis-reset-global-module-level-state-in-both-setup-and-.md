---
id: 0298
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.003715+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Reset global/module-level state in both setup and teardown

Fixtures that touch shared singletons (e.g., `_rate_limit_until`) must reset them at fixture start *and* at teardown.

Example: Use an autouse conftest fixture to ensure `module._rate_limit_until = 0` runs before and after every test.

**Why:** Stale state from a prior test leaks into later tests, causing order-dependent flakiness invisible in isolation.

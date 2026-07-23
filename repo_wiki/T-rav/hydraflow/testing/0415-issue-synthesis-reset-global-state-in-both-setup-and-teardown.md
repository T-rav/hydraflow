---
id: 0415
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.846346+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
superseded_by: 0451
---

# Reset global state in both setup and teardown

Fixtures that touch shared singletons must reset them at fixture start and at teardown.

Example: Use an autouse conftest fixture to ensure `module._rate_limit_until = 0` runs before and after every test.

**Why:** Stale state from a prior test leaks into later tests, causing order-dependent flakiness invisible in isolation.

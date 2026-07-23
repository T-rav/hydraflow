---
id: 0424
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.852419+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
superseded_by: 0451
---

# Enforce 50/30-line limits on handlers and wiring

Keep handler functions to ≤ 50 lines and registration wiring to ≤ 30 lines. Extract nested closures into instance methods to hold nesting to ≤ 3 levels.

Example: Enforce via AST-based tests with ±3 line tolerance. See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Functions exceeding these limits are difficult to test in isolation; deeply nested closures cannot be mocked independently.

---
id: 0346
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.494541+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Enforce 50/30-line limits on handlers and wiring

Keep handler functions to ≤ 50 lines and registration wiring to ≤ 30 lines. Extract nested closures into instance methods to hold nesting to ≤ 3 levels.

Example: Enforce via AST-based tests with ±3 line tolerance. See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Functions exceeding these limits are difficult to test in isolation; deeply nested closures cannot be mocked independently.

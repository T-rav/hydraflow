---
id: 0181
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.583532+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Enforce 50-line handler and 30-line wiring limits for testability

Handler functions must stay under 50 lines; registration wiring under 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Enforce via AST-based tests with ±3 line tolerance.

See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Deep nesting and long handlers are hard to unit-test in isolation; the limit forces decomposition that makes individual behaviors independently testable.

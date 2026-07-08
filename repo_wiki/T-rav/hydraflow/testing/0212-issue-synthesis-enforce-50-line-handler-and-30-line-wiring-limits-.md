---
id: 0212
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.792854+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Enforce 50-line handler and 30-line wiring limits for testability

Handler functions must stay under 50 lines; registration wiring under 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Enforce via AST-based tests with ±3 line tolerance.

See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Deep nesting and long handlers are hard to unit-test in isolation; the limit forces decomposition that makes individual behaviors independently testable.

---
id: 0121
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.087982+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Enforce 50-line handler and 30-line wiring limits for testability

Handler functions must stay under 50 lines; registration wiring under 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Enforce via AST-based tests with ±3 line tolerance.

See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Deep nesting and long handlers are hard to unit-test in isolation; the limit forces decomposition that makes individual behaviors independently testable.

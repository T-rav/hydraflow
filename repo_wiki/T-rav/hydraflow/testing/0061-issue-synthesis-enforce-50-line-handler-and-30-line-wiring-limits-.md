---
id: 0061
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.215098+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Enforce 50-line handler and 30-line wiring limits for testability

Handler functions must stay under 50 lines; registration wiring under 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels.

Enforce via AST-based tests with ±3 line tolerance (see: Allow ±3 line drift in AST-based structure assertions).

**Why:** Deep nesting and long handlers are hard to unit-test in isolation; the limit forces decomposition that makes individual behaviors independently testable.

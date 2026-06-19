---
id: 0091
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.277304+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Enforce 50-line handler and 30-line wiring limits for testability

Handler functions must stay under 50 lines; registration wiring under 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Enforce via AST-based tests with ±3 line tolerance. See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Deep nesting and long handlers are hard to unit-test in isolation; the limit forces decomposition that makes individual behaviors independently testable.

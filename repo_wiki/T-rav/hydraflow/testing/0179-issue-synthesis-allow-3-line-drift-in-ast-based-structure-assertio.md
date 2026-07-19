---
id: 0179
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.582809+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Allow ±3 line drift in AST-based structure assertions

For tests that verify code structure by parsing source ASTs (e.g., checking function length or nesting depth), allow ±3 line tolerance.

Example: Assert `len(func.body) <= 53` rather than `<= 50` to account for blank lines and decorator variations.

See also: testing — Enforce 50-line handler and 30-line wiring limits for testability.

**Why:** Exact line-count assertions redden CI on whitespace-only diffs, creating maintenance noise without improving correctness.

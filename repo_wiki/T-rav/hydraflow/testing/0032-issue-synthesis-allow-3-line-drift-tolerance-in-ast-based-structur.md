---
id: 0032
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.831626+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Allow ±3 line drift tolerance in AST-based structure assertions

For tests that verify code structure by parsing source ASTs (e.g., checking function length or nesting depth), allow ±3 line tolerance.

Example: Assert `len(func.body) <= 53` rather than `<= 50` to account for blank lines and decorator variations.

**Why:** Exact line-count assertions redden CI on whitespace-only diffs, creating maintenance noise without improving correctness.

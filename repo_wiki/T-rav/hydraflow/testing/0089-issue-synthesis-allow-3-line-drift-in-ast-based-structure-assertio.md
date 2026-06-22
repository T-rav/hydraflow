---
id: 0089
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.276741+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Allow ±3 line drift in AST-based structure assertions

For tests that verify code structure by parsing source ASTs (e.g., checking function length or nesting depth), allow ±3 line tolerance.

Example: Assert `len(func.body) <= 53` rather than `<= 50` to account for blank lines and decorator variations. See also: testing — Enforce 50-line handler and 30-line wiring limits for testability.

**Why:** Exact line-count assertions redden CI on whitespace-only diffs, creating maintenance noise without improving correctness.

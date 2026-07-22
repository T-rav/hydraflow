---
id: 0487
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.380298+00:00
status: superseded
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
superseded_by: 0492
---

# Allow ±3 line drift in AST-based structure assertions

For tests that verify code structure by parsing source ASTs (e.g., checking function length), allow ±3 line tolerance.

Example: Assert `len(func.body) <= 53` rather than `<= 50` to account for blank lines and decorator variations. See also: testing — Enforce 50/30-line limits on handlers and wiring.

**Why:** Exact line-count assertions redden CI on whitespace-only diffs, creating maintenance noise without improving correctness.

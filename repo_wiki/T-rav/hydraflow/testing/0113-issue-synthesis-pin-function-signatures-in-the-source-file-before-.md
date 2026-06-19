---
id: 0113
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.085270+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Pin function signatures in the source file before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first; write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Then write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

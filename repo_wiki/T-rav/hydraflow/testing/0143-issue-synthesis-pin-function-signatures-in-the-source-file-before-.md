---
id: 0143
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.437778+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Pin function signatures in the source file before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first; write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Then write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

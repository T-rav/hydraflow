---
id: 0398
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.743296+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Pin function signatures before writing callers

Decide the authoritative signature (argument order, return tuple shape) in the source file first; then write docs and tests to match.

Example: 1. Write the function stub. 2. Copy its exact signature into the docstring. 3. Write the test.

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime, and both artifacts may be wrong.

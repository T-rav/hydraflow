---
id: 0054
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.213854+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Pin function signatures in the source file before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first; write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Then write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

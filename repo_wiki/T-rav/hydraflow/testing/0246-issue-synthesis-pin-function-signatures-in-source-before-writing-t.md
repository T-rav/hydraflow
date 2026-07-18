---
id: 0246
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:14:32.525142+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# Pin function signatures in source before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first, then write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

---
id: 0184
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.783288+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Pin function signatures in the source file before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first; then write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

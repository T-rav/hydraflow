---
id: 0281
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.495124+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Pin function signatures before writing callers or tests

Decide the authoritative signature (argument order, return tuple shape) in the source file first; then write docs and tests to match.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime, and both artifacts may be wrong.

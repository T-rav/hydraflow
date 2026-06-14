---
id: 0027
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.830691+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Pin function signatures in the source file before writing tests or docs

Decide the authoritative signature (argument order, return tuple shape) in the source file first; write docs and tests to match that single source of truth.

1. Write the function stub
2. Copy its exact signature into the docstring
3. Then write the test

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime — both artifacts can be wrong simultaneously.

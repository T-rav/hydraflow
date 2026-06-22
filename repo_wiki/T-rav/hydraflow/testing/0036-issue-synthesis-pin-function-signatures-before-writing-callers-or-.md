---
id: 0036
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.412085+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Pin function signatures before writing callers or tests

Write the function stub first, copy its exact signature into the docstring, then write the test.

- `_diff_targets` was documented as `(a, b) -> (warnings, to_add)` in one artifact
- Tests called it as `(a) -> (to_add, warnings)` — different arity and reversed return order

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime, and both artifacts may be wrong.

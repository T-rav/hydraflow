---
id: 2529
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.980964+00:00
status: active
corroborations: 1
supersedes: 2340
---

# Gate contract tests pin exact context sets — widen on changes

`tests/test_gates_contract.py`, `tests/test_gates_resolve.py`, and `tests/test_gates_capability_resolve.py` contain exact-set assertions that must be widened whenever the staging or main gate set changes.

Example: after adding `CI Gate`, staging set became `Detect Changes`, `discover-projects`, `CI Gate`; main stays at 14 contexts excluding `CI Gate`. Update `test_contract_staging_requires_two_contexts`, `test_resolve_staging_contexts`, and `test_real_contract_output_unchanged_by_filtering`.

**Why:** Count-based test names go stale silently; missed exact-set pins cause `make quality` failures after contract changes.

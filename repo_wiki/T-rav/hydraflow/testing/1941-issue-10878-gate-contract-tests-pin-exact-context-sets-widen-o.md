---
id: 1941
topic: testing
source_issue: 10878
source_phase: plan
created_at: 2026-07-31T07:10:49.839622+00:00
status: superseded
corroborations: 1
superseded_by: 2066
---

# Gate contract tests pin exact context sets — widen on contract changes

`tests/test_gates_contract.py`, `tests/test_gates_resolve.py`, and `tests/test_gates_capability_resolve.py` contain exact-set assertions that must be widened whenever the staging or main gate set changes.

- `test_contract_staging_requires_two_contexts` — rename off the count, update expected set
- `test_resolve_staging_contexts` — update expected list
- `test_real_contract_output_unchanged_by_filtering` — update expected list

After adding `CI Gate`, staging set became `Detect Changes`, `discover-projects`, `CI Gate`; main stays at 14 contexts excluding `CI Gate`.

**Why:** Count-based test names go stale silently; missed exact-set pins cause `make quality` failures after contract changes.

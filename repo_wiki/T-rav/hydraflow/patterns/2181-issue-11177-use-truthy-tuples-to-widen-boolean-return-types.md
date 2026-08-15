---
id: 2181
topic: patterns
source_issue: 11177
source_phase: plan
created_at: 2026-08-14T22:44:18.538089+00:00
status: superseded
corroborations: 1
superseded_by: 2297
---

# Use truthy tuples to widen boolean return types

When expanding a boolean return type to carry data, return a tuple to maintain backward compatibility with boolean checks. In `src/escape/auto_diagnose.py`, `_trace_commit` returns pin paths as a tuple instead of a bool, allowing `if _trace_commit(...)` to keep working while gathering evidence.

**Why:** Avoids breaking existing callers like `adds_regression_pin` and prevents data migrations in old ledger notes.

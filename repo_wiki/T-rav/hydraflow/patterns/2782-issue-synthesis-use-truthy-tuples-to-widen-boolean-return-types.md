---
id: 2782
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:02.145509+00:00
status: superseded
corroborations: 1
supersedes: 2659
superseded_by: 2911
---

# Use truthy tuples to widen boolean return types

When expanding a boolean return type to carry data, return a tuple to maintain backward compatibility with boolean checks.

Example: In `src/escape/auto_diagnose.py`, `_trace_commit` returns pin paths as a tuple instead of a bool, allowing `if _trace_commit(...)` to keep working while gathering evidence.

**Why:** Avoids breaking existing callers like `adds_regression_pin` and prevents data migrations in old ledger notes.

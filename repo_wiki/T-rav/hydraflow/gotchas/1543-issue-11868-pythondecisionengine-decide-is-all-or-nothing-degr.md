---
id: 1543
topic: gotchas
source_issue: 11868
source_phase: plan
created_at: 2026-09-01T03:50:35.471554+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# PythonDecisionEngine.decide() is all-or-nothing — degrade, don't drop

Rule: Call `decide(facts, charter=None)` once per standard inside `try/except DecisionEngineError`, emitting an `undecidable` row with `str(exc)` for failures.

- `UnsupportedStandardError` and `MissingFactError` are both `DecisionEngineError` subclasses
- A failed standard still appears in the output with its exception message
- Other standards' rows survive the failure

**Why:** Dropping a standard on error hides charter-declared standards from the generated page, breaking the "visible, not silent" guarantee.

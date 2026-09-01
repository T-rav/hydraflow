---
id: 1547
topic: gotchas
source_issue: 11865
source_phase: plan
created_at: 2026-09-01T05:42:59.837490+00:00
status: active
corroborations: 1
---

# Caretaker filing predicate must diverge from fatal predicate

Keep the set of findings that file issues (`filed_findings`) separate from the set that dirties the report (`fatal_findings`). In `charter_drift_caretaker_loop.py`, both `_file_repo_drift` and `_reconcile_resolved` must iterate `filed_findings`, not `fatal_findings`.

- Advisory class `FINDING_ACTOR_WITHOUT_LOOP` lives in `filed_findings` but not `fatal_findings`
- If reconcile reads `fatal_findings`, its active set is narrower than filing → issue is created and auto-closed every tick → infinite churn

**Why:** The charter caretaker collapsed both predicates onto `fatal_findings`; any advisory class that files but doesn't dirty the report gets refiled and closed on every tick, burying the human signal the advisory exists to raise.

---
id: 2371
topic: testing
source_issue: 11084
source_phase: plan
created_at: 2026-08-14T05:53:19.138441+00:00
status: superseded
corroborations: 1
superseded_by: 2560
---

# Run full make quality, not file-targeted pytest subsets

Verify `escape_ledger_loop.py` changes with full `make quality`, never a file-targeted pytest subset.
- `escape_ledger_loop.py` is shared by 5+ regression pins; a subset shipped the #8460 class of miss.
- Must-be-green set: `tests/regressions/test_issue_11084.py`, `tests/test_escape_auto_diagnose.py`, `tests/regressions/test_escape_auto_diagnose_before_human.py`, `tests/test_escape_ledger_loop.py`, `tests/test_escape_ledger.py`, `tests/scenarios/test_escape_ledger_scenario.py`.
**Why:** Targeted subsets miss regressions in sibling pins that share the module under edit.

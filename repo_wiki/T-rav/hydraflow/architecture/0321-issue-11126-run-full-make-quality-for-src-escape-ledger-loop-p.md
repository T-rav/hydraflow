---
id: 0321
topic: architecture
source_issue: 11126
source_phase: plan
created_at: 2026-08-14T11:53:15.166038+00:00
status: active
corroborations: 1
---

# Run full make quality for src/escape_ledger_loop.py changes

Always run full `make quality` when modifying `src/escape_ledger_loop.py` — never a file-targeted subset.

- This module is shared by 5+ test pins across `tests/test_escape_ledger_loop.py`, `tests/test_escape_auto_diagnose.py`, and other escape suites.
- A file-targeted run passes while breaking `INCONCLUSIVE`-pinned contracts and sibling escape pins.

**Why:** File-targeted test subsets miss cross-module contract violations that only surface in the full suite.

---
id: 0244
topic: architecture
source_issue: 10749
source_phase: plan
created_at: 2026-07-27T22:53:04.998264+00:00
status: active
corroborations: 1
---

# Run full make quality for escape_ledger_loop changes

Do not run a file-targeted test subset for changes touching `src/escape_ledger_loop.py`; it is shared by 5+ regression pins.

- Run `make quality` in full per CLAUDE.md.
- Verify with `tests/regressions/test_issue_10574.py`, `tests/test_escape_ledger.py`, `tests/test_escape_ledger_loop.py`, `tests/scenarios/test_escape_ledger_scenario.py`.

**Why:** A file-targeted subset misses cross-cutting regressions in the shared loop module.

---
id: 2560
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.455737+00:00
status: active
corroborations: 1
supersedes: 2371,2418
---

# Run full make quality for shared loop modules, not subsets

Verify changes to `src/escape_ledger_loop.py` and other shared loop modules with full `make quality`, never a file-targeted pytest subset.

Example: `escape_ledger_loop.py` is shared by 5+ regression pins; must-be-green set includes `tests/regressions/test_issue_11084.py`, `tests/test_escape_ledger_loop.py`, `tests/test_escape_ledger.py`, `tests/scenarios/test_escape_ledger_scenario.py`. Regression pins use real temp git repos, `FakeGitHub`, and `tests/helpers.make_bg_loop_deps`.

**Why:** Shared modules have cross-cutting coverage; targeted subsets silently miss regressions in dependent pins.

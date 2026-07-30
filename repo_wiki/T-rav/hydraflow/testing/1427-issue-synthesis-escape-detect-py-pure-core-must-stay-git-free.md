---
id: 1427
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T00:21:29.142843+00:00
status: superseded
corroborations: 1
supersedes: 1352
superseded_by: 1515
---

# escape/detect.py pure core must stay git-free

src/escape/detect.py classification logic (has_skip_regression gate, _origin_pointer) must only operate on already-extracted commit data, never shell out to git/gh/subprocess.

Example: tests/test_escape_ledger.py is unit-level pure-function tests; tests/scenarios/test_escape_ledger_scenario.py uses MockWorld fakes only, no real git/GitHub/subprocess calls. Regression spec tests/regressions/test_issue_10498.py is written red-first.

**Why:** Keeping the detector pure lets it be unit-tested deterministically and reused by callers (like audit.crosslink) without pulling in process/network dependencies.

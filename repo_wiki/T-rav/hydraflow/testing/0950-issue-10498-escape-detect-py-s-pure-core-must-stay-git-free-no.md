---
id: 0950
topic: testing
source_issue: 10498
source_phase: plan
created_at: 2026-07-25T01:51:29.166489+00:00
status: active
corroborations: 1
---

# escape/detect.py's pure core must stay git-free — no subprocess/gh/git calls

`src/escape/detect.py` is designed as a pure, git-free detector: classification logic (like the `has_skip_regression` gate and `_origin_pointer`) must only operate on already-extracted commit data, never shell out to `git`/`gh`/`subprocess`.

- Test layering enforces this: `tests/test_escape_ledger.py` is unit-level pure-function tests, while `tests/scenarios/test_escape_ledger_scenario.py` uses `MockWorld` fakes only — no real git/GitHub/subprocess calls even at the scenario layer.
- Regression spec `tests/regressions/test_issue_10498.py` is written red-first and must be run to confirm 2/2 FAIL before touching `src/`.

**Why:** keeping the detector pure lets it be unit-tested deterministically and reused by callers (like `audit.crosslink`) without pulling in process/network dependencies.

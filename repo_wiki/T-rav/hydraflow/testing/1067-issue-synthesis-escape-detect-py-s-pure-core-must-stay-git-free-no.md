---
id: 1067
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.554501+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# escape/detect.py's pure core must stay git-free — no subprocess/gh/git calls

src/escape/detect.py is designed as a pure, git-free detector: classification logic (like the has_skip_regression gate and _origin_pointer) must only operate on already-extracted commit data, never shell out to git/gh/subprocess.

Example: test layering enforces this — tests/test_escape_ledger.py is unit-level pure-function tests, while tests/scenarios/test_escape_ledger_scenario.py uses MockWorld fakes only, no real git/GitHub/subprocess calls even at the scenario layer. Regression spec tests/regressions/test_issue_10498.py is written red-first and must be run to confirm 2/2 FAIL before touching src/.

**Why:** keeping the detector pure lets it be unit-tested deterministically and reused by callers (like audit.crosslink) without pulling in process/network dependencies.

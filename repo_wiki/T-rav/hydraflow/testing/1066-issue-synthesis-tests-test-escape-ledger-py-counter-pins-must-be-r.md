---
id: 1066
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.553084+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# tests/test_escape_ledger.py counter-pins must be rewritten, not deleted

When src/escape/detect.py's originating_pr semantics change, the counter-pin assertions in tests/test_escape_ledger.py (e.g. originating_pr == 777 near line 207, == 4242 near line 196) must be rewritten to assert the new semantics, not simply removed.

**Why:** a deleted assertion still shows a green test run but proves nothing about the new behavior — this was flagged as a named pre-mortem risk in the #10498 plan, where deletion would silently pass while validating nothing.

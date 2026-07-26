---
id: 1069
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.557460+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# test_latest_by_id_collapses_to_last_appended_row doesn't isolate collapse basis

In tests/test_escape_ledger.py:494, test_latest_by_id_collapses_to_last_appended_row gives both rows the same detected_at, so it can't tell whether read_latest() collapses by append position or by timestamp — a regression that flips the collapse key would still pass.

Example: strengthen with a 3-row chain plus a case where the earlier-position row has a later detected_at, to pin position-based (not timestamp-based) collapse semantics.

**Why:** an ambiguous fixture lets a semantically wrong collapse implementation pass the existing test, akin to weak dict.get(k, default) assertions.
